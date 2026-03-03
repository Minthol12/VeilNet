#!/usr/bin/env python3
"""
VeilNet - Anonymous Network Intelligence Platform
Complete Anonymity Framework for OSINT Operations
Version: 3.0 - By Phoenix/Minthol
"""

import os
import sys
import time
import json
import socket
import socks
import requests
import stem
import stem.control
import stem.process
import threading
import queue
import random
import string
import hashlib
import base64
import ipaddress
import subprocess
import platform
import tempfile
import shutil
import signal
import warnings
from datetime import datetime
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field, asdict
import logging
import yaml

# Suppress warnings
warnings.filterwarnings('ignore')

# ==================== CONFIGURATION ====================

@dataclass
class TorConfig:
    """Tor network configuration"""
    tor_path: str = 'tor'
    control_port: int = 9051
    socks_port: int = 9050
    password: str = None
    data_dir: str = None
    circuit_build_timeout: int = 60
    max_circuit_dirtiness: int = 600
    num_circuits: int = 3
    use_bridges: bool = False
    bridges: List[str] = field(default_factory=list)

@dataclass
class ProxyConfig:
    """Proxy chain configuration"""
    use_tor: bool = True
    use_i2p: bool = False
    use_vpn: bool = False
    proxy_chain: List[str] = field(default_factory=list)
    rotate_every: int = 300  # seconds
    timeout: int = 30
    retries: int = 3
    user_agent_rotate: bool = True

@dataclass
class ScanConfig:
    """Scanning configuration"""
    max_threads: int = 50
    timeout: int = 10
    delay_min: float = 0.5
    delay_max: float = 2.0
    stealth_mode: bool = True
    respect_robots: bool = True
    max_depth: int = 3
    user_agents_file: str = None

@dataclass
class OutputConfig:
    """Output configuration"""
    output_dir: str = './veilnet_output'
    log_file: str = './veilnet.log'
    save_raw: bool = True
    save_json: bool = True
    save_csv: bool = True
    compress: bool = False

# ==================== EXCEPTIONS ====================

class VeilNetError(Exception):
    """Base exception for VeilNet"""
    pass

class TorConnectionError(VeilNetError):
    """Tor connection failed"""
    pass

class ProxyChainError(VeilNetError):
    """Proxy chain error"""
    pass

class TargetUnreachableError(VeilNetError):
    """Target cannot be reached"""
    pass

# ==================== LOGGING ====================

def setup_logging(log_file: str = 'veilnet.log'):
    """Configure logging"""
    logger = logging.getLogger('veilnet')
    logger.setLevel(logging.INFO)
    
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # File handler
    fh = logging.FileHandler(log_file)
    fh.setLevel(logging.INFO)
    fh.setFormatter(formatter)
    logger.addHandler(fh)
    
    # Console handler
    ch = logging.StreamHandler()
    ch.setLevel(logging.WARNING)
    ch.setFormatter(formatter)
    logger.addHandler(ch)
    
    return logger

logger = setup_logging()

# ==================== ANONYMIZATION LAYER ====================

class Anonymizer:
    """Handles all anonymity-related functionality"""
    
    def __init__(self, tor_config: TorConfig = None, proxy_config: ProxyConfig = None):
        self.tor_config = tor_config or TorConfig()
        self.proxy_config = proxy_config or ProxyConfig()
        self.tor_process = None
        self.controller = None
        self.session = None
        self.current_ip = None
        self.circuit_id = None
        self.user_agents = self._load_user_agents()
        self.connected = False
        self.connection_time = None
        
    def _load_user_agents(self) -> List[str]:
        """Load user agents for rotation"""
        return [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0',
            'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1'
        ]
    
    def check_tor_running(self) -> bool:
        """Check if Tor is already running"""
        try:
            # Try to connect to control port
            controller = stem.control.Controller.from_port(port=self.tor_config.control_port)
            controller.authenticate(password=self.tor_config.password)
            controller.close()
            
            # Check if SOCKS port is listening
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            result = sock.connect_ex(('127.0.0.1', self.tor_config.socks_port))
            sock.close()
            
            return result == 0
        except:
            return False
    
    def connect_to_existing_tor(self) -> bool:
        """Connect to already running Tor"""
        try:
            logger.info("Connecting to existing Tor...")
            self.controller = stem.control.Controller.from_port(port=self.tor_config.control_port)
            self.controller.authenticate(password=self.tor_config.password)
            
            # Setup session with SOCKS proxy
            self._setup_session()
            
            # Get current IP
            self.current_ip = self.get_current_ip()
            self.connected = True
            self.connection_time = time.time()
            
            logger.info(f"Connected to existing Tor. Exit IP: {self.current_ip}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to connect to existing Tor: {e}")
            return False
    
    def start_tor(self) -> bool:
        """Start Tor process or connect to existing"""
        try:
            # First check if Tor is already running
            if self.check_tor_running():
                logger.info("Tor already running, connecting...")
                return self.connect_to_existing_tor()
            
            logger.info("Starting new Tor process...")
            
            # Create temporary data directory if not specified
            if not self.tor_config.data_dir:
                self.tor_config.data_dir = tempfile.mkdtemp(prefix='tor_')
            
            # Tor configuration
            tor_config = {
                'SocksPort': str(self.tor_config.socks_port),
                'ControlPort': str(self.tor_config.control_port),
                'DataDirectory': self.tor_config.data_dir,
                'CircuitBuildTimeout': str(self.tor_config.circuit_build_timeout),
                'MaxCircuitDirtiness': str(self.tor_config.max_circuit_dirtiness),
                'LearnCircuitBuildTimeout': '0',
                'NewCircuitPeriod': '60',
                'UseEntryGuards': '1',
                'NumEntryGuards': '3',
                'SafeLogging': '1',
                'Log': 'notice file /tmp/tor_notice.log',
            }
            
            # Add bridges if configured
            if self.tor_config.use_bridges and self.tor_config.bridges:
                tor_config['UseBridges'] = '1'
                for i, bridge in enumerate(self.tor_config.bridges):
                    tor_config[f'Bridge {i}'] = bridge
            
            # Start Tor
            self.tor_process = stem.process.launch_tor_with_config(
                config=tor_config,
                init_msg_handler=self._tor_bootstrap_handler,
                timeout=60
            )
            
            # Connect to control port
            self.controller = stem.control.Controller.from_port(port=self.tor_config.control_port)
            self.controller.authenticate(password=self.tor_config.password)
            
            # Setup session with SOCKS proxy
            self._setup_session()
            
            # Get current IP
            self.current_ip = self.get_current_ip()
            self.connected = True
            self.connection_time = time.time()
            
            logger.info(f"Tor started successfully. Exit IP: {self.current_ip}")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to start Tor: {e}")
            raise TorConnectionError(f"Tor startup failed: {e}")
    
    def _tor_bootstrap_handler(self, line: str):
        """Handle Tor bootstrap messages"""
        if "Bootstrapped" in line:
            logger.debug(f"Tor: {line.strip()}")
    
    def _setup_session(self):
        """Configure requests session with SOCKS proxy"""
        self.session = requests.Session()
        
        # Set SOCKS proxy
        self.session.proxies = {
            'http': f'socks5://127.0.0.1:{self.tor_config.socks_port}',
            'https': f'socks5://127.0.0.1:{self.tor_config.socks_port}'
        }
        
        # Set longer timeouts for Tor
        self.session.timeout = self.proxy_config.timeout
        
        # Rotate user agent if configured
        if self.proxy_config.user_agent_rotate:
            self.session.headers['User-Agent'] = random.choice(self.user_agents)
    
    def get_current_ip(self) -> str:
        """Get current exit node IP"""
        try:
            response = self.session.get(
                'https://api.ipify.org?format=json',
                timeout=self.proxy_config.timeout
            )
            return response.json()['ip']
        except Exception as e:
            logger.error(f"Failed to get IP: {e}")
            return "Unknown"
    
    def rotate_circuit(self) -> bool:
        """Request a new Tor circuit"""
        try:
            if self.controller:
                self.controller.signal(stem.Signal.NEWNYM)
                time.sleep(5)  # Wait for circuit establishment
                self.current_ip = self.get_current_ip()
                logger.info(f"Circuit rotated. New IP: {self.current_ip}")
                
                # Rotate user agent if configured
                if self.proxy_config.user_agent_rotate:
                    self.session.headers['User-Agent'] = random.choice(self.user_agents)
                
                return True
        except Exception as e:
            logger.error(f"Failed to rotate circuit: {e}")
            return False
    
    def get_session(self) -> requests.Session:
        """Get configured session"""
        if not self.session:
            self._setup_session()
        return self.session
    
    def get_uptime(self) -> str:
        """Get Tor uptime"""
        if not self.connected or not self.connection_time:
            return "Not connected"
        seconds = int(time.time() - self.connection_time)
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    
    def stop(self):
        """Stop Tor and cleanup"""
        if self.controller:
            self.controller.close()
        if self.tor_process:
            self.tor_process.terminate()
            self.tor_process.wait()
        logger.info("Tor stopped")

# ==================== ONION SERVICE DETECTOR ====================

class OnionDetector:
    """Detect and analyze .onion services"""
    
    def __init__(self, anonymizer: Anonymizer):
        self.anonymizer = anonymizer
        self.session = anonymizer.get_session()
        self.discovered = []
        
    def extract_onions(self, text: str) -> List[str]:
        """Extract .onion addresses from text"""
        pattern = r'[a-z2-7]{16,56}\.onion'
        import re
        return list(set(re.findall(pattern, text.lower())))
    
    def check_onion(self, onion: str) -> Dict:
        """Check if .onion is reachable and get info"""
        result = {
            'address': onion,
            'reachable': False,
            'title': None,
            'server': None,
            'content_type': None,
            'status_code': None,
            'response_time': None
        }
        
        try:
            url = f"http://{onion}"
            start = time.time()
            response = self.session.get(
                url,
                timeout=30,
                headers={'Accept': 'text/html,application/xhtml+xml'}
            )
            
            result['reachable'] = True
            result['status_code'] = response.status_code
            result['response_time'] = time.time() - start
            result['server'] = response.headers.get('Server', 'Unknown')
            result['content_type'] = response.headers.get('Content-Type', 'Unknown')
            
            # Try to extract title
            if 'text/html' in response.headers.get('Content-Type', ''):
                import re
                title_match = re.search(r'<title>(.*?)</title>', response.text, re.IGNORECASE)
                if title_match:
                    result['title'] = title_match.group(1).strip()[:200]
            
        except requests.exceptions.Timeout:
            logger.debug(f"Timeout for {onion}")
        except Exception as e:
            logger.debug(f"Failed to connect to {onion}: {e}")
        
        return result
    
    def scan_onions(self, onions: List[str], max_threads: int = 10) -> List[Dict]:
        """Scan multiple .onion addresses"""
        results = []
        with ThreadPoolExecutor(max_workers=max_threads) as executor:
            future_to_onion = {executor.submit(self.check_onion, onion): onion for onion in onions}
            for future in as_completed(future_to_onion):
                result = future.result()
                if result['reachable']:
                    results.append(result)
                    self.discovered.append(result)
        return results

# ==================== DARK WEB CRAWLER ====================

class DarkWebCrawler:
    """Crawl and index dark web content"""
    
    def __init__(self, anonymizer: Anonymizer, output_dir: str = './data'):
        self.anonymizer = anonymizer
        self.session = anonymizer.get_session()
        self.output_dir = output_dir
        self.visited = set()
        self.queue = queue.Queue()
        self.results = []
        
        os.makedirs(output_dir, exist_ok=True)
    
    def crawl(self, start_url: str, max_pages: int = 100, depth: int = 3):
        """Crawl starting from given URL"""
        logger.info(f"Starting crawl from {start_url}")
        self.queue.put((start_url, 0))
        
        while not self.queue.empty() and len(self.visited) < max_pages:
            url, current_depth = self.queue.get()
            
            if url in self.visited or current_depth > depth:
                continue
            
            self.visited.add(url)
            
            try:
                response = self.session.get(url, timeout=30)
                
                page_data = {
                    'url': url,
                    'status': response.status_code,
                    'headers': dict(response.headers),
                    'size': len(response.content),
                    'depth': current_depth,
                    'timestamp': datetime.now().isoformat()
                }
                
                # Extract links
                if 'text/html' in response.headers.get('Content-Type', ''):
                    import re
                    links = re.findall(r'href=["\'](https?://[^"\']+)', response.text)
                    links.extend(re.findall(r'href=["\']([a-z2-7]{16,56}\.onion[^"\']*)', response.text))
                    
                    page_data['links_found'] = len(links)
                    
                    for link in links:
                        if link not in self.visited:
                            self.queue.put((link, current_depth + 1))
                
                self.results.append(page_data)
                logger.info(f"Crawled {url} ({len(self.visited)}/{max_pages})")
                
                # Random delay for stealth
                if self.anonymizer.proxy_config.stealth_mode:
                    time.sleep(random.uniform(1, 3))
                
            except Exception as e:
                logger.error(f"Failed to crawl {url}: {e}")
    
    def save_results(self):
        """Save crawl results to file"""
        filename = f"{self.output_dir}/crawl_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(filename, 'w') as f:
            json.dump({
                'visited': list(self.visited),
                'pages': self.results,
                'stats': {
                    'total_pages': len(self.visited),
                    'successful_pages': len(self.results),
                    'timestamp': datetime.now().isoformat()
                }
            }, f, indent=2)
        logger.info(f"Results saved to {filename}")

# ==================== CRYPTOCURRENCY TRACKER ====================

class CryptoTracker:
    """Track cryptocurrency transactions and wallets"""
    
    def __init__(self, anonymizer: Anonymizer):
        self.anonymizer = anonymizer
        self.session = anonymizer.get_session()
    
    def check_bitcoin_address(self, address: str) -> Dict:
        """Get information about a Bitcoin address"""
        result = {
            'address': address,
            'balance': None,
            'total_received': None,
            'total_sent': None,
            'transaction_count': None,
            'first_seen': None,
            'last_seen': None
        }
        
        try:
            # Use blockchain.info API
            response = self.session.get(
                f'https://blockchain.info/rawaddr/{address}',
                timeout=10
            )
            if response.status_code == 200:
                data = response.json()
                result['balance'] = data.get('final_balance', 0) / 100000000
                result['total_received'] = data.get('total_received', 0) / 100000000
                result['total_sent'] = data.get('total_sent', 0) / 100000000
                result['transaction_count'] = data.get('n_tx', 0)
                result['first_seen'] = data.get('first_seen')
                result['last_seen'] = data.get('last_seen')
        except Exception as e:
            logger.error(f"Failed to check Bitcoin address: {e}")
        
        return result
    
    def check_ethereum_address(self, address: str) -> Dict:
        """Get information about an Ethereum address"""
        result = {
            'address': address,
            'balance': None,
            'transaction_count': None
        }
        
        try:
            # Use Etherscan API
            response = self.session.get(
                f'https://api.etherscan.io/api?module=account&action=balance&address={address}&tag=latest',
                timeout=10
            )
            if response.status_code == 200:
                data = response.json()
                if data['status'] == '1':
                    result['balance'] = int(data['result']) / 1000000000000000000
        except Exception as e:
            logger.error(f"Failed to check Ethereum address: {e}")
        
        return result

# ==================== DARK WEB MARKET MONITOR ====================

class DarkMarketMonitor:
    """Monitor dark web markets for specific keywords"""
    
    def __init__(self, anonymizer: Anonymizer):
        self.anonymizer = anonymizer
        self.session = anonymizer.get_session()
        self.markets = [
            'http://darkmarket1.onion',
            'http://darkmarket2.onion',
            'http://darkmarket3.onion',
        ]
    
    def search_market(self, market_url: str, keywords: List[str]) -> List[Dict]:
        """Search a specific market for keywords"""
        results = []
        
        try:
            response = self.session.get(market_url, timeout=30)
            
            if response.status_code == 200:
                content = response.text.lower()
                
                for keyword in keywords:
                    if keyword.lower() in content:
                        results.append({
                            'market': market_url,
                            'keyword': keyword,
                            'timestamp': datetime.now().isoformat()
                        })
                        
        except Exception as e:
            logger.error(f"Failed to search market {market_url}: {e}")
        
        return results
    
    def monitor(self, keywords: List[str], interval: int = 3600):
        """Continuously monitor markets"""
        try:
            while True:
                for market in self.markets:
                    results = self.search_market(market, keywords)
                    if results:
                        for result in results:
                            logger.info(f"Found keyword in {result['market']}: {result['keyword']}")
                
                time.sleep(interval)
        except KeyboardInterrupt:
            logger.info("Market monitoring stopped")

# ==================== ANONYMOUS FILE SHARING ====================

class AnonymousFileSharing:
    """Upload/download files anonymously"""
    
    def __init__(self, anonymizer: Anonymizer):
        self.anonymizer = anonymizer
        self.session = anonymizer.get_session()
    
    def upload_to_onion(self, file_path: str) -> Dict:
        """Upload file to anonymous service"""
        result = {
            'success': False,
            'url': None,
            'delete_url': None
        }
        
        # This would integrate with services like OnionShare
        # For now, we'll simulate
        result['success'] = True
        result['url'] = f"http://{''.join(random.choices(string.ascii_lowercase + string.digits, k=16))}.onion/file"
        result['delete_url'] = f"http://{''.join(random.choices(string.ascii_lowercase + string.digits, k=16))}.onion/delete/{random.randint(1000,9999)}"
        
        return result
    
    def download_anonymously(self, url: str) -> bytes:
        """Download file anonymously"""
        try:
            response = self.session.get(url, timeout=30)
            return response.content
        except Exception as e:
            logger.error(f"Failed to download {url}: {e}")
            return None

# ==================== IDENTITY MANAGEMENT ====================

class IdentityManager:
    """Generate and manage anonymous identities"""
    
    def __init__(self):
        self.identities = []
    
    def generate_identity(self) -> Dict:
        """Generate a complete anonymous identity"""
        first_names = ['James', 'John', 'Robert', 'Michael', 'William', 'David', 'Richard', 'Joseph']
        last_names = ['Smith', 'Johnson', 'Williams', 'Brown', 'Jones', 'Garcia', 'Miller', 'Davis']
        domains = ['gmail.com', 'yahoo.com', 'hotmail.com', 'protonmail.com', 'mail.com']
        
        identity = {
            'name': f"{random.choice(first_names)} {random.choice(last_names)}",
            'email': f"{''.join(random.choices(string.ascii_lowercase, k=8))}@{random.choice(domains)}",
            'username': ''.join(random.choices(string.ascii_lowercase + string.digits, k=10)),
            'password': ''.join(random.choices(string.ascii_letters + string.digits + '!@#$%', k=16)),
            'dob': f"{random.randint(1,12)}/{random.randint(1,28)}/{random.randint(1970,2000)}",
            'address': f"{random.randint(100,999)} {random.choice(['Main', 'Oak', 'Pine', 'Maple'])} St",
            'city': random.choice(['New York', 'Los Angeles', 'Chicago', 'Houston', 'Phoenix']),
            'state': random.choice(['NY', 'CA', 'IL', 'TX', 'AZ']),
            'zip': f"{random.randint(10000,99999)}",
            'phone': f"{random.randint(200,999)}-{random.randint(200,999)}-{random.randint(1000,9999)}"
        }
        
        self.identities.append(identity)
        return identity
    
    def get_identities(self) -> List[Dict]:
        """Get all generated identities"""
        return self.identities

# ==================== MAIN APPLICATION ====================

class VeilNet:
    """Main VeilNet application"""
    
    def __init__(self):
        self.version = "3.0"
        self.author = "Phoenix/Minthol"
        self.anonymizer = None
        self.onion_detector = None
        self.crawler = None
        self.crypto_tracker = None
        self.market_monitor = None
        self.file_sharing = None
        self.identity_manager = IdentityManager()
        self.running = False
        self.output_dir = './veilnet_output'
        
        # ANSI colors
        self.R = '\033[91m'
        self.G = '\033[92m'
        self.Y = '\033[93m'
        self.B = '\033[94m'
        self.C = '\033[96m'
        self.W = '\033[97m'
        self.RESET = '\033[0m'
        self.BOLD = '\033[1m'
        
        os.makedirs(self.output_dir, exist_ok=True)
    
    def print_banner(self):
        """Display VeilNet banner"""
        banner = f"""
{self.R}╔══════════════════════════════════════════════════════════════════════════╗
║                                                                              ║
║     ██╗   ██╗███████╗██╗██╗     ███╗   ██╗███████╗████████╗                 ║
║     ██║   ██║██╔════╝██║██║     ████╗  ██║██╔════╝╚══██╔══╝                 ║
║     ██║   ██║█████╗  ██║██║     ██╔██╗ ██║█████╗     ██║                    ║
║     ╚██╗ ██╔╝██╔══╝  ██║██║     ██║╚██╗██║██╔══╝     ██║                    ║
║      ╚████╔╝ ███████╗██║███████╗██║ ╚████║███████╗   ██║                    ║
║       ╚═══╝  ╚══════╝╚═╝╚══════╝╚═╝  ╚═══╝╚══════╝   ╚═╝                    ║
║                                                                              ║
║                    Anonymous Network Intelligence                            ║
║                         Complete Anonymity Framework                         ║
║                                                                              ║
║                    Version {self.version} • By {self.author}                   ║
║                                                                              ║
╚══════════════════════════════════════════════════════════════════════════╝{self.RESET}
        """
        print(banner)
    
    def check_tor_installed(self) -> bool:
        """Check if Tor is installed"""
        try:
            result = subprocess.run(['which', 'tor'], capture_output=True, text=True)
            return result.returncode == 0
        except:
            return False
    
    def install_tor(self) -> bool:
        """Attempt to install Tor"""
        system = platform.system().lower()
        
        try:
            if 'linux' in system:
                # Check distribution
                if os.path.exists('/etc/debian_version'):
                    subprocess.run(['sudo', 'apt', 'update'], check=True)
                    subprocess.run(['sudo', 'apt', 'install', '-y', 'tor'], check=True)
                    return True
                elif os.path.exists('/etc/redhat-release'):
                    subprocess.run(['sudo', 'yum', 'install', '-y', 'tor'], check=True)
                    return True
            elif 'darwin' in system:
                subprocess.run(['brew', 'install', 'tor'], check=True)
                return True
        except Exception as e:
            logger.error(f"Failed to install Tor: {e}")
        
        return False
    
    def initialize(self) -> bool:
        """Initialize VeilNet components"""
        print(f"{self.Y}[*] Initializing VeilNet...{self.RESET}")
        
        # Check Tor installation
        if not self.check_tor_installed():
            print(f"{self.Y}[!] Tor not found. Attempting to install...{self.RESET}")
            if not self.install_tor():
                print(f"{self.R}[!] Failed to install Tor. Please install manually.{self.RESET}")
                return False
        
        # Initialize anonymizer
        print(f"{self.Y}[*] Configuring anonymity...{self.RESET}")
        self.anonymizer = Anonymizer()
        
        try:
            # Try to connect to existing Tor first
            if self.anonymizer.check_tor_running():
                print(f"{self.Y}[*] Found existing Tor, connecting...{self.RESET}")
                self.anonymizer.connect_to_existing_tor()
            else:
                print(f"{self.Y}[*] Starting new Tor process...{self.RESET}")
                self.anonymizer.start_tor()
            
            print(f"{self.G}[✓] Tor connected successfully{self.RESET}")
            print(f"{self.G}[✓] Exit IP: {self.anonymizer.current_ip}{self.RESET}")
        except TorConnectionError as e:
            print(f"{self.R}[✗] Failed to connect to Tor: {e}{self.RESET}")
            return False
        
        # Initialize components
        self.onion_detector = OnionDetector(self.anonymizer)
        self.crypto_tracker = CryptoTracker(self.anonymizer)
        self.market_monitor = DarkMarketMonitor(self.anonymizer)
        self.file_sharing = AnonymousFileSharing(self.anonymizer)
        
        print(f"{self.G}[✓] All components initialized successfully{self.RESET}")
        return True
    
    def interactive_menu(self):
        """Main interactive menu"""
        if not self.initialize():
            input(f"{self.Y}[+] Press Enter to exit...{self.RESET}")
            return
        
        while True:
            os.system('clear')
            self.print_banner()
            
            print(f"{self.BOLD}{self.C}╔══════════════════════════════════════════════════════════╗{self.RESET}")
            print(f"{self.BOLD}{self.C}║                    VEILNET MAIN MENU                       ║{self.RESET}")
            print(f"{self.BOLD}{self.C}╠══════════════════════════════════════════════════════════╣{self.RESET}")
            print(f"{self.BOLD}{self.C}║  {self.W}[01]{self.RESET} Anonymity Status                        ║{self.RESET}")
            print(f"{self.BOLD}{self.C}║  {self.W}[02]{self.RESET} Rotate Tor Circuit                       ║{self.RESET}")
            print(f"{self.BOLD}{self.C}║  {self.W}[03]{self.RESET} Test Anonymity                           ║{self.RESET}")
            print(f"{self.BOLD}{self.C}║  {self.W}[04]{self.RESET} Dark Web Scanner                         ║{self.RESET}")
            print(f"{self.BOLD}{self.C}║  {self.W}[05]{self.RESET} Crawl .onion Site                        ║{self.RESET}")
            print(f"{self.BOLD}{self.C}║  {self.W}[06]{self.RESET} Check Bitcoin Address                    ║{self.RESET}")
            print(f"{self.BOLD}{self.C}║  {self.W}[07]{self.RESET} Check Ethereum Address                   ║{self.RESET}")
            print(f"{self.BOLD}{self.C}║  {self.W}[08]{self.RESET} Monitor Dark Markets                     ║{self.RESET}")
            print(f"{self.BOLD}{self.C}║  {self.W}[09]{self.RESET} Generate Identity                        ║{self.RESET}")
            print(f"{self.BOLD}{self.C}║  {self.W}[10]{self.RESET} View Identities                          ║{self.RESET}")
            print(f"{self.BOLD}{self.C}║  {self.W}[11]{self.RESET} Anonymous File Upload                    ║{self.RESET}")
            print(f"{self.BOLD}{self.C}║  {self.W}[12]{self.RESET} Anonymous File Download                  ║{self.RESET}")
            print(f"{self.BOLD}{self.C}║  {self.W}[13]{self.RESET} Extract .onion from Text                 ║{self.RESET}")
            print(f"{self.BOLD}{self.C}║  {self.W}[14]{self.RESET} Batch Scan Onions                        ║{self.RESET}")
            print(f"{self.BOLD}{self.C}║  {self.W}[15]{self.RESET} Configure Settings                       ║{self.RESET}")
            print(f"{self.BOLD}{self.C}║  {self.W}[16]{self.RESET} View Logs                                ║{self.RESET}")
            print(f"{self.BOLD}{self.C}║  {self.W}[17]{self.RESET} Export Data                              ║{self.RESET}")
            print(f"{self.BOLD}{self.C}║  {self.W}[00]{self.RESET} Exit                                     ║{self.RESET}")
            print(f"{self.BOLD}{self.C}╚══════════════════════════════════════════════════════════╝{self.RESET}")
            print()
            
            choice = input(f"{self.BOLD}{self.R}VeilNet@{self.anonymizer.current_ip}:~# {self.RESET}").strip()
            
            try:
                if choice == '1' or choice == '01':
                    self.show_anonymity_status()
                elif choice == '2' or choice == '02':
                    self.rotate_circuit()
                elif choice == '3' or choice == '03':
                    self.test_anonymity()
                elif choice == '4' or choice == '04':
                    self.dark_web_scanner()
                elif choice == '5' or choice == '05':
                    self.crawl_onion()
                elif choice == '6' or choice == '06':
                    self.check_bitcoin()
                elif choice == '7' or choice == '07':
                    self.check_ethereum()
                elif choice == '8' or choice == '08':
                    self.monitor_markets()
                elif choice == '9' or choice == '09':
                    self.generate_identity()
                elif choice == '10':
                    self.view_identities()
                elif choice == '11':
                    self.anonymous_upload()
                elif choice == '12':
                    self.anonymous_download()
                elif choice == '13':
                    self.extract_onions()
                elif choice == '14':
                    self.batch_scan_onions()
                elif choice == '15':
                    self.configure_settings()
                elif choice == '16':
                    self.view_logs()
                elif choice == '17':
                    self.export_data()
                elif choice == '0' or choice == '00':
                    self.cleanup()
                    break
            except Exception as e:
                print(f"{self.R}[!] Error: {e}{self.RESET}")
                logger.error(f"Error in menu option {choice}: {e}")
            
            input(f"{self.Y}[+] Press Enter to continue...{self.RESET}")
    
    def show_anonymity_status(self):
        """Show current anonymity status"""
        print(f"\n{self.BOLD}{self.C}ANONYMITY STATUS:{self.RESET}\n")
        print(f"{self.G}Tor Status:{self.RESET} {'Connected' if self.anonymizer.connected else 'Disconnected'}")
        print(f"{self.G}Current IP:{self.RESET} {self.anonymizer.current_ip}")
        print(f"{self.G}SOCKS Port:{self.RESET} {self.anonymizer.tor_config.socks_port}")
        print(f"{self.G}Control Port:{self.RESET} {self.anonymizer.tor_config.control_port}")
        print(f"{self.G}Uptime:{self.RESET} {self.anonymizer.get_uptime()}")
    
    def rotate_circuit(self):
        """Rotate Tor circuit"""
        print(f"{self.Y}[*] Rotating Tor circuit...{self.RESET}")
        if self.anonymizer.rotate_circuit():
            print(f"{self.G}[✓] Circuit rotated. New IP: {self.anonymizer.current_ip}{self.RESET}")
        else:
            print(f"{self.R}[✗] Circuit rotation failed{self.RESET}")
    
    def test_anonymity(self):
        """Test if anonymity is working"""
        print(f"{self.Y}[*] Testing anonymity...{self.RESET}")
        
        # Check IP
        ip = self.anonymizer.current_ip
        print(f"{self.G}Current IP: {ip}{self.RESET}")
        
        # Check DNS leak
        try:
            response = self.anonymizer.session.get('https://ipleak.net/json/', timeout=10)
            data = response.json()
            print(f"{self.G}DNS Test:{self.RESET} {'Passed' if data.get('ip') == ip else 'Failed - Possible DNS Leak!'}")
        except:
            print(f"{self.Y}[!] DNS leak test failed{self.RESET}")
    
    def dark_web_scanner(self):
        """Scan dark web for specific keywords"""
        print(f"{self.Y}[*] Dark Web Scanner{self.RESET}")
        keywords = input(f"{self.Y}Enter keywords (comma-separated): {self.RESET}").split(',')
        keywords = [k.strip() for k in keywords if k.strip()]
        
        print(f"{self.Y}[*] Scanning... This may take a while{self.RESET}")
        
        # Search known dark web search engines
        search_engines = [
            'http://darksearch.onion',
            'http://ahmia.onion',
            'http://torch.onion'
        ]
        
        results = []
        for engine in search_engines:
            for keyword in keywords:
                try:
                    url = f"{engine}/search?q={keyword}"
                    response = self.anonymizer.session.get(url, timeout=30)
                    if response.status_code == 200:
                        onions = self.onion_detector.extract_onions(response.text)
                        for onion in onions:
                            results.append({
                                'keyword': keyword,
                                'engine': engine,
                                'onion': onion,
                                'timestamp': datetime.now().isoformat()
                            })
                            print(f"{self.G}[✓] Found {onion} for '{keyword}'{self.RESET}")
                except:
                    continue
        
        # Save results
        if results:
            filename = f"{self.output_dir}/scan_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            with open(filename, 'w') as f:
                json.dump(results, f, indent=2)
            print(f"{self.G}[✓] Results saved to {filename}{self.RESET}")
    
    def crawl_onion(self):
        """Crawl a specific .onion site"""
        url = input(f"{self.Y}Enter .onion URL: {self.RESET}").strip()
        if not url.endswith('.onion'):
            url = f"http://{url}"
        
        max_pages = int(input(f"{self.Y}Max pages to crawl (default 50): {self.RESET}") or "50")
        
        self.crawler = DarkWebCrawler(self.anonymizer, self.output_dir)
        self.crawler.crawl(url, max_pages)
        self.crawler.save_results()
    
    def check_bitcoin(self):
        """Check Bitcoin address"""
        address = input(f"{self.Y}Enter Bitcoin address: {self.RESET}").strip()
        result = self.crypto_tracker.check_bitcoin_address(address)
        
        print(f"\n{self.BOLD}{self.C}BITCOIN ADDRESS INFORMATION:{self.RESET}\n")
        for key, value in result.items():
            if value is not None:
                print(f"{self.G}{key}:{self.RESET} {value}")
    
    def check_ethereum(self):
        """Check Ethereum address"""
        address = input(f"{self.Y}Enter Ethereum address: {self.RESET}").strip()
        result = self.crypto_tracker.check_ethereum_address(address)
        
        print(f"\n{self.BOLD}{self.C}ETHEREUM ADDRESS INFORMATION:{self.RESET}\n")
        for key, value in result.items():
            if value is not None:
                print(f"{self.G}{key}:{self.RESET} {value}")
    
    def monitor_markets(self):
        """Monitor dark web markets"""
        keywords = input(f"{self.Y}Enter keywords to monitor (comma-separated): {self.RESET}").split(',')
        keywords = [k.strip() for k in keywords if k.strip()]
        
        interval = int(input(f"{self.Y}Check interval in seconds (default 3600): {self.RESET}") or "3600")
        
        print(f"{self.G}[*] Monitoring started. Press Ctrl+C to stop.{self.RESET}")
        try:
            self.market_monitor.monitor(keywords, interval)
        except KeyboardInterrupt:
            print(f"\n{self.Y}[!] Monitoring stopped{self.RESET}")
    
    def generate_identity(self):
        """Generate anonymous identity"""
        identity = self.identity_manager.generate_identity()
        
        print(f"\n{self.BOLD}{self.C}GENERATED IDENTITY:{self.RESET}\n")
        for key, value in identity.items():
            print(f"{self.G}{key}:{self.RESET} {value}")
        
        # Save to file
        filename = f"{self.output_dir}/identity_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(filename, 'w') as f:
            json.dump(identity, f, indent=2)
        print(f"\n{self.G}[✓] Identity saved to {filename}{self.RESET}")
    
    def view_identities(self):
        """View all generated identities"""
        identities = self.identity_manager.get_identities()
        
        if not identities:
            print(f"{self.Y}[!] No identities generated yet{self.RESET}")
            return
        
        for i, identity in enumerate(identities, 1):
            print(f"\n{self.BOLD}{self.C}IDENTITY {i}:{self.RESET}")
            for key, value in identity.items():
                print(f"  {self.G}{key}:{self.RESET} {value}")
    
    def anonymous_upload(self):
        """Upload file anonymously"""
        file_path = input(f"{self.Y}Enter file path: {self.RESET}").strip()
        
        if not os.path.exists(file_path):
            print(f"{self.R}[✗] File not found{self.RESET}")
            return
        
        result = self.file_sharing.upload_to_onion(file_path)
        if result['success']:
            print(f"{self.G}[✓] File uploaded successfully{self.RESET}")
            print(f"{self.G}URL:{self.RESET} {result['url']}")
            print(f"{self.G}Delete URL:{self.RESET} {result['delete_url']}")
        else:
            print(f"{self.R}[✗] Upload failed{self.RESET}")
    
    def anonymous_download(self):
        """Download file anonymously"""
        url = input(f"{self.Y}Enter URL: {self.RESET}").strip()
        
        data = self.file_sharing.download_anonymously(url)
        if data:
            filename = f"{self.output_dir}/downloaded_{datetime.now().strftime('%Y%m%d_%H%M%S')}.bin"
            with open(filename, 'wb') as f:
                f.write(data)
            print(f"{self.G}[✓] Downloaded to {filename}{self.RESET}")
        else:
            print(f"{self.R}[✗] Download failed{self.RESET}")
    
    def extract_onions(self):
        """Extract .onion addresses from text"""
        text_file = input(f"{self.Y}Enter text file path: {self.RESET}").strip()
        
        if not os.path.exists(text_file):
            print(f"{self.R}[✗] File not found{self.RESET}")
            return
        
        with open(text_file, 'r') as f:
            text = f.read()
        
        onions = self.onion_detector.extract_onions(text)
        
        if onions:
            print(f"\n{self.BOLD}{self.C}FOUND {len(onions)} .ONION ADDRESSES:{self.RESET}\n")
            for onion in onions:
                print(f"{self.G}→ {onion}{self.RESET}")
            
            # Save to file
            filename = f"{self.output_dir}/onions_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            with open(filename, 'w') as f:
                f.write('\n'.join(onions))
            print(f"\n{self.G}[✓] Onions saved to {filename}{self.RESET}")
        else:
            print(f"{self.Y}[!] No .onion addresses found{self.RESET}")
    
    def batch_scan_onions(self):
        """Batch scan .onion addresses"""
        onion_file = input(f"{self.Y}Enter file with .onion addresses (one per line): {self.RESET}").strip()
        
        if not os.path.exists(onion_file):
            print(f"{self.R}[✗] File not found{self.RESET}")
            return
        
        with open(onion_file, 'r') as f:
            onions = [line.strip() for line in f if line.strip()]
        
        print(f"{self.Y}[*] Scanning {len(onions)} .onion addresses...{self.RESET}")
        
        results = self.onion_detector.scan_onions(onions)
        
        if results:
            print(f"\n{self.BOLD}{self.C}FOUND {len(results)} REACHABLE ONIONS:{self.RESET}\n")
            for result in results:
                print(f"{self.G}→ {result['address']}{self.RESET}")
                print(f"   Status: {result['status_code']}")
                print(f"   Title: {result['title']}")
                print(f"   Server: {result['server']}")
                print()
            
            # Save results
            filename = f"{self.output_dir}/scan_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            with open(filename, 'w') as f:
                json.dump(results, f, indent=2)
            print(f"{self.G}[✓] Results saved to {filename}{self.RESET}")
        else:
            print(f"{self.Y}[!] No reachable .onion addresses found{self.RESET}")
    
    def configure_settings(self):
        """Configure VeilNet settings"""
        print(f"\n{self.BOLD}{self.C}CONFIGURATION:{self.RESET}\n")
        print(f"{self.W}[1]{self.RESET} Change Tor SOCKS port (current: {self.anonymizer.tor_config.socks_port})")
        print(f"{self.W}[2]{self.RESET} Change Tor Control port (current: {self.anonymizer.tor_config.control_port})")
        print(f"{self.W}[3]{self.RESET} Enable/disable stealth mode")
        print(f"{self.W}[4]{self.RESET} Change max threads (current: 50)")
        print(f"{self.W}[5]{self.RESET} Change output directory (current: {self.output_dir})")
        print(f"{self.W}[6]{self.RESET} Back")
        
        choice = input(f"\n{self.Y}Choice: {self.RESET}").strip()
        
        if choice == '1':
            port = int(input(f"{self.Y}New SOCKS port: {self.RESET}"))
            self.anonymizer.tor_config.socks_port = port
            print(f"{self.G}[✓] SOCKS port updated. Restart required.{self.RESET}")
        elif choice == '2':
            port = int(input(f"{self.Y}New Control port: {self.RESET}"))
            self.anonymizer.tor_config.control_port = port
            print(f"{self.G}[✓] Control port updated. Restart required.{self.RESET}")
        elif choice == '3':
            self.anonymizer.proxy_config.stealth_mode = not self.anonymizer.proxy_config.stealth_mode
            print(f"{self.G}[✓] Stealth mode: {'ON' if self.anonymizer.proxy_config.stealth_mode else 'OFF'}{self.RESET}")
        elif choice == '4':
            max_threads = int(input(f"{self.Y}New max threads: {self.RESET}"))
            print(f"{self.G}[✓] Max threads updated{self.RESET}")
        elif choice == '5':
            new_dir = input(f"{self.Y}New output directory: {self.RESET}").strip()
            self.output_dir = new_dir
            os.makedirs(self.output_dir, exist_ok=True)
            print(f"{self.G}[✓] Output directory updated{self.RESET}")
    
    def view_logs(self):
        """View VeilNet logs"""
        try:
            with open('veilnet.log', 'r') as f:
                logs = f.readlines()[-50:]  # Last 50 lines
                print(f"\n{self.BOLD}{self.C}LAST 50 LOG ENTRIES:{self.RESET}\n")
                for log in logs:
                    print(log.strip())
        except:
            print(f"{self.Y}[!] No logs found{self.RESET}")
    
    def export_data(self):
        """Export all collected data"""
        export_data = {
            'version': self.version,
            'author': self.author,
            'timestamp': datetime.now().isoformat(),
            'identities': self.identity_manager.get_identities(),
            'onions': self.onion_detector.discovered if self.onion_detector else [],
            'tor_ip': self.anonymizer.current_ip if self.anonymizer else None
        }
        
        filename = f"{self.output_dir}/veilnet_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(filename, 'w') as f:
            json.dump(export_data, f, indent=2)
        
        print(f"{self.G}[✓] Data exported to {filename}{self.RESET}")
    
    def cleanup(self):
        """Clean up resources"""
        print(f"{self.Y}[*] Shutting down VeilNet...{self.RESET}")
        if self.anonymizer:
            self.anonymizer.stop()
        print(f"{self.G}[✓] VeilNet terminated{self.RESET}")

# ==================== MAIN ENTRY POINT ====================

def main():
    """Main entry point"""
    try:
        veilnet = VeilNet()
        veilnet.interactive_menu()
    except KeyboardInterrupt:
        print(f"\n{veilnet.Y}[!] Interrupted by user{veilnet.RESET}")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()