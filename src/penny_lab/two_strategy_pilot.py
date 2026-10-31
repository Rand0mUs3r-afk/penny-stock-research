"""Branch experiment: unchanged multi-provider pipeline, uptrend pullback only.

Legacy module name retained so the existing workflow command stays compatible.
"""
from .config import Config
from . import multi_pilot

EXPERIMENT_STRATEGIES = ('uptrend_pullback',)

def experiment_config(*args, **kwargs):
    kwargs['strategies'] = EXPERIMENT_STRATEGIES
    return Config(*args, **kwargs)

def main():
    original = multi_pilot.Config
    try:
        multi_pilot.Config = experiment_config
        multi_pilot.main()
    finally:
        multi_pilot.Config = original

if __name__ == '__main__':
    main()
