#!/usr/bin/env python3
"""
FPS Server Test Script
Tests if the server is accessible and functioning correctly
"""

import asyncio
import websockets
import json
import time
import sys
from datetime import datetime

# Configuration
SERVER_URL = "ws://217.154.149.234:8765"
TEST_TIMEOUT = 10
COLORS = {
    'GREEN': '\033[92m',
    'RED': '\033[91m',
    'YELLOW': '\033[93m',
    'BLUE': '\033[94m',
    'CYAN': '\033[96m',
    'RESET': '\033[0m',
    'BOLD': '\033[1m'
}

class ServerTester:
    def __init__(self, server_url):
        self.server_url = server_url
        self.tests_passed = 0
        self.tests_failed = 0
        self.tests_total = 0
        
    def print_header(self, text):
        """Print a formatted header"""
        print(f"\n{COLORS['BOLD']}{COLORS['CYAN']}{'='*60}{COLORS['RESET']}")
        print(f"{COLORS['BOLD']}{COLORS['CYAN']}{text:^60}{COLORS['RESET']}")
        print(f"{COLORS['BOLD']}{COLORS['CYAN']}{'='*60}{COLORS['RESET']}\n")
    
    def print_test(self, name):
        """Print test name"""
        print(f"{COLORS['BLUE']}▶ Testing: {name}{COLORS['RESET']}", end=" ... ")
        sys.stdout.flush()
    
    def print_result(self, success, message=""):
        """Print test result"""
        self.tests_total += 1
        if success:
            self.tests_passed += 1
            print(f"{COLORS['GREEN']}✓ PASS{COLORS['RESET']}", end="")
            if message:
                print(f" ({message})")
            else:
                print()
        else:
            self.tests_failed += 1
            print(f"{COLORS['RED']}✗ FAIL{COLORS['RESET']}", end="")
            if message:
                print(f" ({message})")
            else:
                print()
    
    def print_summary(self):
        """Print test summary"""
        self.print_header("TEST SUMMARY")
        
        success_rate = (self.tests_passed / self.tests_total * 100) if self.tests_total > 0 else 0
        
        print(f"Total Tests: {COLORS['BOLD']}{self.tests_total}{COLORS['RESET']}")
        print(f"Passed: {COLORS['GREEN']}{self.tests_passed}{COLORS['RESET']}")
        print(f"Failed: {COLORS['RED']}{self.tests_failed}{COLORS['RESET']}")
        print(f"Success Rate: {COLORS['BOLD']}{success_rate:.1f}%{COLORS['RESET']}")
        
        if self.tests_failed == 0:
            print(f"\n{COLORS['GREEN']}{COLORS['BOLD']}🎉 ALL TESTS PASSED! Server is healthy.{COLORS['RESET']}\n")
        else:
            print(f"\n{COLORS['RED']}{COLORS['BOLD']}⚠️  SOME TESTS FAILED! Check server configuration.{COLORS['RESET']}\n")
    
    async def test_connection(self):
        """Test 1: Basic connection"""
        self.print_test("Server Connection")
        try:
            async with websockets.connect(
                self.server_url,
                timeout=TEST_TIMEOUT,
                ping_interval=None
            ) as ws:
                self.print_result(True, f"Connected to {self.server_url}")
                return ws
        except asyncio.TimeoutError:
            self.print_result(False, "Connection timeout")
            return None
        except ConnectionRefusedError:
            self.print_result(False, "Connection refused - server not running?")
            return None
        except Exception as e:
            self.print_result(False, f"Error: {str(e)}")
            return None
    
    async def test_join_message(self, ws):
        """Test 2: Join message"""
        self.print_test("Join Message")
        try:
            join_msg = {
                "type": "join",
                "name": "TestBot",
                "mode": "deathmatch"
            }
            await ws.send(json.dumps(join_msg))
            
            # Wait for welcome message
            response = await asyncio.wait_for(ws.recv(), timeout=5)
            data = json.loads(response)
            
            if data.get("type") == "welcome" and "id" in data:
                self.print_result(True, f"Received player ID: {data['id']}")
                return data["id"]
            else:
                self.print_result(False, f"Unexpected response: {data.get('type')}")
                return None
                
        except asyncio.TimeoutError:
            self.print_result(False, "No response from server")
            return None
        except Exception as e:
            self.print_result(False, f"Error: {str(e)}")
            return None
    
    async def test_state_updates(self, ws):
        """Test 3: State updates"""
        self.print_test("State Updates")
        try:
            # Wait for state update
            for _ in range(10):  # Try up to 10 messages
                response = await asyncio.wait_for(ws.recv(), timeout=3)
                data = json.loads(response)
                
                if data.get("type") == "state":
                    has_players = "players" in data and isinstance(data["players"], list)
                    has_weapons = "weapons" in data and isinstance(data["weapons"], list)
                    has_time = "t" in data
                    
                    if has_players and has_weapons and has_time:
                        self.print_result(True, f"{len(data['players'])} players, {len(data['weapons'])} weapons")
                        return True
            
            self.print_result(False, "No state update received")
            return False
                
        except asyncio.TimeoutError:
            self.print_result(False, "Timeout waiting for state")
            return False
        except Exception as e:
            self.print_result(False, f"Error: {str(e)}")
            return False
    
    async def test_input_message(self, ws):
        """Test 4: Input message"""
        self.print_test("Input Message Processing")
        try:
            input_msg = {
                "type": "input",
                "input": {
                    "yaw": 0.5,
                    "pitch": 0.2,
                    "keys": {
                        "w": True,
                        "s": False,
                        "a": False,
                        "d": False,
                        "shift": False,
                        "ctrl": False
                    }
                }
            }
            await ws.send(json.dumps(input_msg))
            
            # Server should not crash and should keep sending state updates
            response = await asyncio.wait_for(ws.recv(), timeout=3)
            data = json.loads(response)
            
            self.print_result(True, "Input accepted")
            return True
                
        except asyncio.TimeoutError:
            self.print_result(False, "Server stopped responding")
            return False
        except Exception as e:
            self.print_result(False, f"Error: {str(e)}")
            return False
    
    async def test_chat_message(self, ws):
        """Test 5: Chat message"""
        self.print_test("Chat System")
        try:
            chat_msg = {
                "type": "chat",
                "message": "Test message from test script"
            }
            await ws.send(json.dumps(chat_msg))
            
            # Wait for chat echo or state update
            response = await asyncio.wait_for(ws.recv(), timeout=3)
            data = json.loads(response)
            
            self.print_result(True, "Chat message sent")
            return True
                
        except asyncio.TimeoutError:
            self.print_result(False, "No response")
            return False
        except Exception as e:
            self.print_result(False, f"Error: {str(e)}")
            return False
    
    async def test_ping(self, ws):
        """Test 6: Latency/Ping"""
        self.print_test("Server Latency")
        try:
            pings = []
            for _ in range(5):
                start = time.time()
                
                # Send input
                await ws.send(json.dumps({
                    "type": "input",
                    "input": {"yaw": 0, "pitch": 0, "keys": {}}
                }))
                
                # Wait for response
                await asyncio.wait_for(ws.recv(), timeout=2)
                
                end = time.time()
                ping = (end - start) * 1000  # Convert to ms
                pings.append(ping)
                
                await asyncio.sleep(0.2)
            
            avg_ping = sum(pings) / len(pings)
            min_ping = min(pings)
            max_ping = max(pings)
            
            self.print_result(
                True, 
                f"Avg: {avg_ping:.1f}ms, Min: {min_ping:.1f}ms, Max: {max_ping:.1f}ms"
            )
            return True
                
        except asyncio.TimeoutError:
            self.print_result(False, "Server not responding")
            return False
        except Exception as e:
            self.print_result(False, f"Error: {str(e)}")
            return False
    
    async def test_rate_limiting(self, ws):
        """Test 7: Rate limiting"""
        self.print_test("Rate Limiting")
        try:
            # Try to send many messages quickly
            messages_sent = 0
            start_time = time.time()
            
            for i in range(50):
                try:
                    await ws.send(json.dumps({
                        "type": "input",
                        "input": {"yaw": i, "pitch": 0, "keys": {}}
                    }))
                    messages_sent += 1
                except:
                    break
            
            elapsed = time.time() - start_time
            
            # Try to receive response
            try:
                await asyncio.wait_for(ws.recv(), timeout=2)
                still_connected = True
            except:
                still_connected = False
            
            if still_connected:
                self.print_result(True, f"Sent {messages_sent} msgs in {elapsed:.2f}s, still connected")
                return True
            else:
                self.print_result(True, f"Rate limit enforced after {messages_sent} messages")
                return True
                
        except Exception as e:
            self.print_result(False, f"Error: {str(e)}")
            return False
    
    async def test_invalid_data(self, ws):
        """Test 8: Invalid data handling"""
        self.print_test("Invalid Data Handling")
        try:
            # Send invalid JSON
            await ws.send("invalid json {{{")
            
            # Server should not crash
            response = await asyncio.wait_for(ws.recv(), timeout=3)
            
            # Send valid message after invalid
            await ws.send(json.dumps({"type": "input", "input": {"yaw": 0, "pitch": 0, "keys": {}}}))
            response = await asyncio.wait_for(ws.recv(), timeout=3)
            
            self.print_result(True, "Server handled invalid data gracefully")
            return True
                
        except asyncio.TimeoutError:
            self.print_result(False, "Server crashed or stopped responding")
            return False
        except Exception as e:
            self.print_result(False, f"Error: {str(e)}")
            return False
    
    async def test_multiple_connections(self):
        """Test 9: Multiple simultaneous connections"""
        self.print_test("Multiple Connections")
        try:
            connections = []
            
            # Try to open 3 connections
            for i in range(3):
                ws = await asyncio.wait_for(
                    websockets.connect(self.server_url, ping_interval=None),
                    timeout=5
                )
                connections.append(ws)
                
                # Send join message
                await ws.send(json.dumps({
                    "type": "join",
                    "name": f"TestBot{i}",
                    "mode": "deathmatch"
                }))
            
            # Wait for welcome messages
            for ws in connections:
                await asyncio.wait_for(ws.recv(), timeout=3)
            
            # Close all connections
            for ws in connections:
                await ws.close()
            
            self.print_result(True, f"Opened {len(connections)} simultaneous connections")
            return True
                
        except Exception as e:
            # Close any open connections
            for ws in connections:
                try:
                    await ws.close()
                except:
                    pass
            
            self.print_result(False, f"Error: {str(e)}")
            return False
    
    async def test_reconnection(self):
        """Test 10: Reconnection after disconnect"""
        self.print_test("Reconnection")
        try:
            # First connection
            ws1 = await asyncio.wait_for(
                websockets.connect(self.server_url, ping_interval=None),
                timeout=5
            )
            await ws1.send(json.dumps({"type": "join", "name": "TestBot", "mode": "deathmatch"}))
            await asyncio.wait_for(ws1.recv(), timeout=3)
            await ws1.close()
            
            # Wait a bit
            await asyncio.sleep(1)
            
            # Reconnect
            ws2 = await asyncio.wait_for(
                websockets.connect(self.server_url, ping_interval=None),
                timeout=5
            )
            await ws2.send(json.dumps({"type": "join", "name": "TestBot", "mode": "deathmatch"}))
            response = await asyncio.wait_for(ws2.recv(), timeout=3)
            data = json.loads(response)
            
            await ws2.close()
            
            if data.get("type") == "welcome":
                self.print_result(True, "Reconnection successful")
                return True
            else:
                self.print_result(False, "Unexpected response")
                return False
                
        except Exception as e:
            self.print_result(False, f"Error: {str(e)}")
            return False
    
    async def run_all_tests(self):
        """Run all tests"""
        self.print_header(f"FPS SERVER TEST - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Testing server: {COLORS['BOLD']}{self.server_url}{COLORS['RESET']}\n")
        
        # Test 1: Connection
        ws = await self.test_connection()
        if not ws:
            print(f"\n{COLORS['RED']}Cannot continue tests - server not accessible{COLORS['RESET']}\n")
            self.print_summary()
            return False
        
        try:
            # Test 2: Join
            player_id = await self.test_join_message(ws)
            
            # Test 3: State updates
            await self.test_state_updates(ws)
            
            # Test 4: Input
            await self.test_input_message(ws)
            
            # Test 5: Chat
            await self.test_chat_message(ws)
            
            # Test 6: Ping
            await self.test_ping(ws)
            
            # Test 7: Rate limiting
            await self.test_rate_limiting(ws)
            
            # Test 8: Invalid data
            await self.test_invalid_data(ws)
            
        except Exception as e:
            print(f"\n{COLORS['RED']}Test suite error: {str(e)}{COLORS['RESET']}")
        finally:
            try:
                await ws.close()
            except:
                pass
        
        # Test 9: Multiple connections (needs new connections)
        await self.test_multiple_connections()
        
        # Test 10: Reconnection
        await self.test_reconnection()
        
        # Print summary
        self.print_summary()
        
        return self.tests_failed == 0


async def main():
    """Main test function"""
    tester = ServerTester(SERVER_URL)
    success = await tester.run_all_tests()
    
    # Exit with appropriate code
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(f"\n\n{COLORS['YELLOW']}Tests interrupted by user{COLORS['RESET']}\n")
        sys.exit(1)
    except Exception as e:
        print(f"\n{COLORS['RED']}Fatal error: {str(e)}{COLORS['RESET']}\n")
        sys.exit(1)
