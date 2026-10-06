"""A ladder that is code, not data: the projector must refuse it without running any of it."""

import os

os.makedirs("/tmp/detection-fixture-was-executed", exist_ok=True)

RUNGS = [dict(id="X0", short="Computed", gate=open("/etc/hostname").read())]
