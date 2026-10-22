"""Frozen service entry point; no frontend or model weights embedded here."""

import multiprocessing
import sys

if __name__ == "__main__":
    multiprocessing.freeze_support()
    if sys.argv[1:] == ["--vision-worker"]:
        from adam.vision.worker import main
    elif sys.argv[1:] in (["--release-launch"], ["--release-apply"]):
        from adam.distribution.cli import main
    else:
        from adam.desktop.service import main
    main()
