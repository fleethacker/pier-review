"""Root pytest config: mock jobs finish instantly in tests."""

import os

os.environ["MOCK_JOB_DELAY_S"] = "0"
