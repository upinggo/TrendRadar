"""Quick test for the email send feature using config.yaml settings."""
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from trendradar.notification.senders import send_to_email

with open(ROOT / "config" / "config.yaml", "r", encoding="utf-8") as f:
    cfg = yaml.safe_load(f)

email_cfg = cfg["notification"]["channels"]["email"]
print("Email config loaded:")
print(f"  from: {email_cfg['from']}")
print(f"  to:   {email_cfg['to']}")
print(f"  smtp: {email_cfg.get('smtp_server') or '(auto)'}:{email_cfg.get('smtp_port') or '(auto)'}")
print()

html_file = ROOT / "output" / "html" / "latest" / "current.html"
if not html_file.exists():
    print(f"HTML report not found: {html_file}")
    sys.exit(1)

print(f"Using HTML report: {html_file}")
print(f"  size: {html_file.stat().st_size / 1024:.1f} KB")
print()

ok = send_to_email(
    from_email=email_cfg["from"],
    password=email_cfg["password"],
    to_email=email_cfg["to"],
    report_type="测试发送",
    html_file_path=str(html_file),
    custom_smtp_server=email_cfg.get("smtp_server") or None,
    custom_smtp_port=email_cfg.get("smtp_port") or None,
)

print()
print("=" * 50)
print(f"Result: {'SUCCESS' if ok else 'FAILED'}")
sys.exit(0 if ok else 1)
