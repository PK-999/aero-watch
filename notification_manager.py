import subprocess
from config_manager import Config

class NotificationManager:
    def __init__(self):
        self.config = Config()
        self.notification_config = self.config.get_notification_config()
        self._tn_permission_warned = False
    
    def send_notification(self, title, message, subtitle="", url=None):
        if not self.notification_config["enabled"]:
            return
        
        # Escape quotes and backslashes for command line and AppleScript
        clean_title = title.replace('\\', '\\\\').replace('"', '\\"')
        clean_message = message.replace('\\', '\\\\').replace('"', '\\"')
        clean_subtitle = subtitle.replace('\\', '\\\\').replace('"', '\\"')
        
        # Attempt 1: terminal-notifier (supports click-to-open URL directly)
        if url:
            try:
                cmd = [
                    'terminal-notifier',
                    '-title', title,
                    '-message', message,
                    '-open', url,
                    '-timeout', str(self.notification_config.get("timeout", 30))
                ]
                if subtitle:
                    cmd.extend(['-subtitle', subtitle])
                if self.notification_config.get("sound"):
                    cmd.extend(['-sound', 'default'])
                
                subprocess.run(cmd, check=True, capture_output=True)
                print(f"Notification sent: {title}")
                print(f"Click notification to open: {url}")
                return
                
            except FileNotFoundError:
                pass
            except subprocess.CalledProcessError as e:
                stderr_output = (e.stderr or b'').decode('utf-8', errors='ignore')
                if "Notifications are turned off" in stderr_output or e.returncode == 3:
                    if not self._tn_permission_warned:
                        print("[!] Tip: terminal-notifier notifications are turned off in macOS System Settings.")
                        print("    To enable click-to-open-URL directly from notifications:")
                        print("    Go to System Settings > Notifications > terminal-notifier and turn on 'Allow Notifications'.")
                        self._tn_permission_warned = True
                else:
                    print(f"terminal-notifier failed: {stderr_output.strip()}")

        # Attempt 2: AppleScript fallback routed via System Events.
        # Routing via 'System Events' prevents macOS from attributing the notification
        # to Script Editor and opening an empty Script Editor window when clicked.
        sub_clause = f' subtitle "{clean_subtitle}"' if clean_subtitle else ''
        beep_clause = '    beep\n' if self.notification_config.get("sound") else ''
        
        applescript = (
            'tell application "System Events"\n'
            f'    display notification "{clean_message}" with title "{clean_title}"{sub_clause}\n'
            f'{beep_clause}'
            'end tell'
        )
        
        try:
            subprocess.run(['osascript', '-e', applescript], check=True)
            print(f"Notification sent: {title}")
            if url:
                print(f"Flight URL: {url}")
                if self.notification_config.get("auto_open_url", False):
                    subprocess.run(['open', url])
        except subprocess.CalledProcessError as e:
            print(f"Error sending notification: {e}")
        except FileNotFoundError:
            print("Error: osascript not found. This script only works on macOS.")

