# Solana Block Fetcher

## Description

This program is designed to monitor and record the performance and size of blocks on the Solana blockchain. It fetches data about Solana blocks, including their size and latency, and stores this information in a PostgreSQL database. It utilizes asynchronous programming to efficiently handle network requests and database operations.

## Features

- Fetches the latest block information from a Solana node.
- Records block size, latency, and potential errors into a PostgreSQL database.
- Monitors the performance and availability of Solana blocks over time.

## Requirements

- Python 3.7+
- aiohttp
- asyncpg
- ping3

## Installation

1. Ensure that Python 3.7 or newer is installed on your system.
2. Install the required Python packages:

```bash
pip install -r requirements.txt
```

## Config

Get a node that is accesable by the program and add the ip to the config file.

```json
{
  "solana": {
    "node_url": "NODE_URL"
  }
}
```

## Run with docker

```bash
docker-compose up -d
```

## Contributing

Contributions to the project are welcome. Please fork the repository, make your changes, and submit a pull request.
