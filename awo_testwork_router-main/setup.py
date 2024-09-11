import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

import router
from setuptools import find_packages, setup

setup(
    name='router',
    version=router.__version__,
    packages=find_packages(where='src'),
    package_dir={'': 'src'},
    install_requires=[
        'fastapi[all]>=0.108.0',
        'uvicorn[standard]>=0.25.0',
        'httpx[socks]>=0.27.0,<1.0.0',
        'debugpy>=1.0.0',
        'redis'
    ],
)
