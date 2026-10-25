import struct

OPENTRACK_FORMAT = "<dddddd"
OPENTRACK_SIZE = struct.calcsize(OPENTRACK_FORMAT)


def pack_opentrack(x=0.0, y=0.0, z=0.0, yaw=0.0, pitch=0.0, roll=0.0):
    return struct.pack(OPENTRACK_FORMAT, x, y, z, yaw, pitch, roll)


def unpack_opentrack(packet):
    return struct.unpack(OPENTRACK_FORMAT, packet)
