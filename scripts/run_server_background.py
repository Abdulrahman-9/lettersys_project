#!/usr/bin/env python
"""
🎯 Django Server Background Service Manager
- Runs server as background process
- Auto-restarts on crash
- Logs all activity to file
- Manages graceful shutdown
"""

import os
import sys
import subprocess
import time
import signal
import logging
from pathlib import Path
from datetime import datetime

# ════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ════════════════════════════════════════════════════════════════════════════
PROJECT_DIR = Path(__file__).parent
LOG_DIR = PROJECT_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

LOG_FILE = LOG_DIR / f"server_{datetime.now().strftime('%Y%m%d')}.log"
PID_FILE = PROJECT_DIR / "server.pid"

# ════════════════════════════════════════════════════════════════════════════
# LOGGING SETUP
# ════════════════════════════════════════════════════════════════════════════
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ════════════════════════════════════════════════════════════════════════════
# BACKGROUND SERVICE MANAGER
# ════════════════════════════════════════════════════════════════════════════
class DjangoServerManager:
    def __init__(self):
        self.process = None
        self.running = True
        self.restart_count = 0
        self.max_restart_delay = 300  # 5 minutes max between restarts
        
    def signal_handler(self, sig, frame):
        """Handle shutdown signals gracefully"""
        logger.info("🛑 Shutdown signal received (Ctrl+C or SIGTERM)")
        self.running = False
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                logger.warning("⚠️  Process didn't stop gracefully, killing...")
                self.process.kill()
        sys.exit(0)
    
    def write_pid(self):
        """Store process ID for monitoring"""
        with open(PID_FILE, 'w') as f:
            f.write(str(os.getpid()))
        logger.info(f"✅ Process ID written to {PID_FILE}")
    
    def start_server(self):
        """Start Django development server"""
        logger.info("🚀 Starting Django server...")
        cmd = [
            sys.executable,
            "manage.py",
            "runserver",
            "0.0.0.0:8000",
            "--nothreading",
            "--noreload"
        ]
        
        try:
            self.process = subprocess.Popen(
                cmd,
                cwd=str(PROJECT_DIR),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                universal_newlines=True
            )
            logger.info(f"✅ Server started with PID {self.process.pid}")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to start server: {e}")
            return False
    
    def monitor_process(self):
        """Monitor server process and restart if crashed"""
        while self.running:
            if self.process is None:
                if not self.start_server():
                    delay = min(2 ** self.restart_count, self.max_restart_delay)
                    logger.warning(f"⏳ Retrying in {delay} seconds... (attempt {self.restart_count + 1})")
                    time.sleep(delay)
                    self.restart_count += 1
                    continue
                self.restart_count = 0
            
            # Check if process is still alive
            poll_result = self.process.poll()
            
            if poll_result is not None:
                logger.warning(f"⚠️  Server crashed with exit code {poll_result}")
                self.process = None
                if self.running:
                    delay = min(2 ** self.restart_count, self.max_restart_delay)
                    logger.info(f"🔄 Auto-restarting in {delay} seconds...")
                    time.sleep(delay)
                    self.restart_count += 1
            else:
                # Process is running, check logs
                try:
                    # Non-blocking read
                    import select
                    if hasattr(select, 'select'):  # Unix-like systems
                        if select.select([self.process.stdout], [], [], 0)[0]:
                            line = self.process.stdout.readline()
                            if line:
                                logger.info(f"[SERVER] {line.rstrip()}")
                except:
                    pass
                
                time.sleep(1)  # Check every second
    
    def run(self):
        """Main execution loop"""
        logger.info("=" * 70)
        logger.info("🌟 Django Background Server Service Started")
        logger.info(f"📁 Project Directory: {PROJECT_DIR}")
        logger.info(f"📝 Log File: {LOG_FILE}")
        logger.info("=" * 70)
        
        # Register signal handlers
        signal.signal(signal.SIGTERM, self.signal_handler)
        signal.signal(signal.SIGINT, self.signal_handler)
        
        # Write PID
        self.write_pid()
        
        # Start monitoring
        try:
            self.monitor_process()
        except Exception as e:
            logger.error(f"❌ Fatal error: {e}", exc_info=True)
        finally:
            if self.process:
                self.process.terminate()
            if PID_FILE.exists():
                PID_FILE.unlink()
            logger.info("🏁 Server service stopped")

# ════════════════════════════════════════════════════════════════════════════
# MAIN ENTRY POINT
# ════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    os.chdir(PROJECT_DIR)
    manager = DjangoServerManager()
    manager.run()
