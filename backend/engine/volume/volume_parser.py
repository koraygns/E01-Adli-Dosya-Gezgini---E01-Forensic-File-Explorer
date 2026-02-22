import pytsk3

class PartitionInfo:
    def __init__(self, addr, start, length, desc):
        self.addr = addr
        self.start = start
        self.length = length
        self.desc = desc

    def to_dict(self):
        return {
            "addr": self.addr,
            "start_sector": self.start,
            "length": self.length,
            "description": self.desc,
        }


def parse_partitions(img_info):
    partitions = []

    try:
        volume = pytsk3.Volume_Info(img_info)

        for part in volume:
            # FTK sol paneli gibi tüm partition slot'larını göster (0MB olanlar da:
            # Partition 0, 1 [unallocated], Partition 2 [FAT32])
            partitions.append(
                PartitionInfo(
                    addr=part.addr,
                    start=part.start,
                    length=part.len,
                    desc=part.desc.decode("utf-8", errors="ignore")
                    if isinstance(part.desc, bytes)
                    else str(part.desc),
                )
            )

    except IOError:
        print("[!] Partition tablosu bulunamadı (raw disk olabilir)")

    return partitions
