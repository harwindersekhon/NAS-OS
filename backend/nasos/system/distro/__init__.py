from nasos.system.distro.base import DistroAdapter
from nasos.system.distro.rhel import RhelDistroAdapter

__all__ = ["DistroAdapter", "RhelDistroAdapter", "get_distro_adapter"]


def get_distro_adapter() -> DistroAdapter:
    return RhelDistroAdapter()
