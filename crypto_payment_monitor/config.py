"""Strict configuration for a read-only crypto monitor."""
from dataclasses import dataclass
import os
from urllib.parse import urlparse

@dataclass(frozen=True)
class Config:
    ethereum_rpc_url: str|None=os.getenv("ETHEREUM_RPC_URL")
    bitcoin_esplora_url: str|None=os.getenv("BITCOIN_ESPLORA_URL")
    ethereum_chain_id: int=int(os.getenv("ETHEREUM_CHAIN_ID","1"))
    bitcoin_network: str=os.getenv("BITCOIN_NETWORK","mainnet")
    poll_interval_seconds: int=int(os.getenv("POLL_INTERVAL_SECONDS","30"))
    confirmations_eth: int=int(os.getenv("CONFIRMATIONS_ETH","12"))
    confirmations_btc: int=int(os.getenv("CONFIRMATIONS_BTC","3"))
    def validate(self):
        if self.poll_interval_seconds<5: raise ValueError("poll interval must be >= 5 seconds")
        if self.confirmations_eth<1 or self.confirmations_btc<1: raise ValueError("confirmation thresholds must be positive")
        if self.bitcoin_network!="mainnet": raise ValueError("initial version supports Bitcoin mainnet only")
        if self.ethereum_chain_id<1: raise ValueError("chain ID must be positive")
        for endpoint in (self.ethereum_rpc_url,self.bitcoin_esplora_url):
            if endpoint is None: continue
            parsed=urlparse(endpoint)
            if parsed.scheme!="https" or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError("provider endpoints must be HTTPS URLs without embedded credentials")
            if parsed.fragment or len(endpoint)>2048: raise ValueError("invalid or oversized provider endpoint")
