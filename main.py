import asyncio
import json
import logging
import re
import socket
import subprocess
import time

import aiohttp
import asyncpg
from ping3 import ping, verbose_ping

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s — %(message)s',
                    datefmt='%Y-%m-%d_%H:%M:%S',
                    handlers=[logging.StreamHandler()])

async def read_config(key):
    with open('config.json') as f:
        data = json.load(f)
    if key == "postgres_url":
        return data["postgres"]["url"]
    elif key == "node_url":
        return data["solana"]["node_url"]
    else:
        return None

async def create_database():
    postgres_url = await read_config("postgres_url")
    conn = await asyncpg.connect(postgres_url)
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS blocks
        (slot INTEGER PRIMARY KEY,
        error INTEGER,
        block_size REAL,
        block_latency_ms REAL)
    ''')
    await conn.close()
    
async def insert_into_database(slot, error, block_size, block_latency_ms):
    postgres_url = await read_config("postgres_url")
    conn = await asyncpg.connect(postgres_url)
    await conn.execute('''
        INSERT INTO blocks (slot, error, block_size, block_latency_ms)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (slot) DO NOTHING
    ''', slot, error, block_size, block_latency_ms)
    await conn.close()

async def fetch_slot(session, url):
    payload = {"jsonrpc": "2.0", "id": 1, "method": "getSlot", "params": [{"commitment": "finalized"}]}
    start_time = time.time()
    async with session.post(url, json=payload) as response:
        latency_ms = (time.time() - start_time) * 1000  # Convert to milliseconds
        if response.status == 200:
            response_data = await response.json()  # Await the json() coroutine and store the result
            size_mb = len(str(response_data)) / (1024 * 1024)  # Convert bytes to megabytes
            return response_data["result"], latency_ms, size_mb
        else:
            raise Exception(f"Failed to fetch slot: {response.status}")

async def fetch_block(session, url, slot, retries=4, delay=0.1):
    for i in range(retries):
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getBlock",
            "params": [slot, {
                "encoding": "json",
                "maxSupportedTransactionVersion":0,
                "transactionDetails": "full",
                "rewards": False,
                "commitment": "finalized"
            }]
        }
        start_time = time.time()
        async with session.post(url, json=payload) as response:
            # The time it takes for your request to reach the server (propagation delay)
            # The time the server takes to process your request and generate a response (processing delay)
            # The time it takes for the response to reach you (propagation delay)
            latency_ms = (time.time() - start_time) * 1000
            if response.status == 200:
                content = await response.read()
                response_data = await response.json()
                if 'error' in response_data:
                    error_message = response_data['error']['message']
                    logging.debug(f"Error fetching block for slot {slot}: {error_message}")
                    await asyncio.sleep(delay)  # Sleep before retrying we might be too fast!!
                    delay =+ 0.1
                else:
                    size_mb = len(content) / (1024 * 1024)
                    return response_data, latency_ms, size_mb
            else:
                raise Exception(f"Failed to fetch block: {response.status}")
    return {'error': True, 'message': 'Block not found after retries'}, 0, 0


async def main():
    async with aiohttp.ClientSession() as session:
        config_url = await read_config('node_url')  # Assume this function correctly retrieves the URL
        node_url = config_url.split('//')[1].split('/')[0]
        node_ip = socket.gethostbyname(node_url)
        # Synchronous ping call - consider finding an async solution
        ping_time = ping(node_ip) #@TODO FIX ME requires root
        #ping_time = 30
        logging.info(40 * "-")
        logging.info(f"Latency checker for Solana node")
        logging.info(f"Ping time to node: {ping_time * 1000:.2f}ms")
        logging.info(f"Commitment level: finalized")
        logging.info(40 * "-")
        
        total_latency = 0
        total_blocks = 0
        total_round_trip_to_long = 1
        total_round_trip_latency_long = 1
        check_counter = 0
        max_latency = 300
        try:
            latest_slot, _, _ = await fetch_slot(session, config_url)
            logging.info(f"Starting with the latest slot: {latest_slot}")
            logging.info(40 * "-")

            lag = 0 
            current_slot = latest_slot
            while True:
                block_data, block_latency_ms, block_size_mb = await fetch_block(session, config_url, current_slot)
                error = 1 if 'error' in block_data else 0
                await insert_into_database(current_slot, error, block_size_mb, block_latency_ms)
                
                if 'error' in block_data:
                    logging.info(f"Skipping slot {current_slot} due to error: {block_data['message']} does not count as failed blocks forking")
                    current_slot += 1
                    logging.info(40 * "-")
                    continue
                
                total_latency += block_latency_ms
                total_blocks += 1

                               
                current_slot += 1  # Move to the next slot
                logging.info(40 * "-")
                # Check how far behind we are periodically
                check_counter += 1

                # This adds 30ms to the latency but we need to be able to compare :(
                new_latest_slot, new_latest_slot_latency, _ = await fetch_slot(session, config_url)
                lag = new_latest_slot - current_slot
                    
                average_latency = total_latency / total_blocks
                total_round_trip_latency = block_latency_ms + new_latest_slot_latency
                
                latency_left = max_latency - block_latency_ms
                logging.debug(f"Block {current_slot} fetched. Latency: {block_latency_ms:.2f}ms, Size: {block_size_mb:.3f} MB we have {latency_left:.2f}ms left")
                logging.debug(f"Updated latest slot: {new_latest_slot} with Latency {new_latest_slot_latency:.2f}ms. We are {lag} slots behind.")
                
                if total_round_trip_latency > max_latency:
                    total_round_trip_to_long += 1
                    total_round_trip_latency_long += total_round_trip_latency
                    logging.debug(f"Round trip latency is too high At {total_round_trip_latency:.2f}ms can't keep up with the network!")
                    
                to_long_roundtrip_latency = total_round_trip_latency_long / total_round_trip_to_long
                percantage_fail = (total_round_trip_to_long / total_blocks) * 100
                logging.info(f"Current slot: {current_slot} | Slow blocks(>300ms): {total_round_trip_to_long} / Total blocks: {total_blocks} | Average: {average_latency:.2f}ms / Average(slow): {to_long_roundtrip_latency:.2f}ms | Lag {lag} slots behind | Failure rate: {percantage_fail:.2f}%")


        except Exception as e:
            logging.info(e)

if __name__ == "__main__":
    asyncio.run(create_database())
    asyncio.run(main())
