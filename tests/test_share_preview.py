"""Public UI preview must not import real application settings or databases."""
import json
import os
import subprocess
import sys


def test_share_preview_is_isolated_from_bot_and_database(tmp_path):
    env = {key: value for key, value in os.environ.items() if not key.startswith(('TELEGRAM_', 'DATABASE_', 'APP_ENV_'))}
    env['APP_ENV_FILE'] = str(tmp_path / 'missing.env')
    result = subprocess.run([sys.executable, '-c', '''
import json, sys
from share_preview import create_app
app = create_app()
paths = [getattr(route, 'path', '') for route in app.routes]
assert 'database.db' not in sys.modules
assert 'config.settings' not in sys.modules
assert 'bot.services.audio_delivery' not in sys.modules
assert not any(path.startswith('/miniapp-api/sets') or path.startswith('/admin') for path in paths)
print(json.dumps(paths))
'''], capture_output=True, text=True, env=env, check=True)
    paths = json.loads(result.stdout)
    assert '/miniapp-api/bootstrap' in paths
    assert '/app/static' in paths
    assert '/app/' in paths
    assert '/docs' not in paths
