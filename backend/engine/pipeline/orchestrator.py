from backend.engine.case.case_manager import CaseManager
from backend.engine.evidence.evidence_manager import EvidenceManager
from backend.engine.io.ewf_reader import open_ewf_image
from backend.engine.volume.volume_parser import parse_partitions
from backend.engine.fs.lazy_tree import LazyTreeEngine


def run_pipeline(e01_path=None):
    print("=== Forensic Engine CLI ===")

    if not e01_path:
        e01_path = input("E01 dosya yolunu gir: ")

    case_manager = CaseManager()
    case_path = case_manager.create_case("Default Case")

    evidence_manager = EvidenceManager()
    evidence_manager.add_evidence(case_path, e01_path)

    print("[*] E01 açılıyor...")
    img = open_ewf_image(e01_path)

    print("[*] Partitionlar okunuyor...")
    partitions = parse_partitions(img)

    print("\n=== PARTITION LIST ===")
    for i, p in enumerate(partitions):
        info = p.to_dict()
        print(f"[{i}] Start: {info['start_sector']}  Size: {info['length']}  Desc: {info['description']}")

    # FAT partition bul
    fat_partition = None
    for p in partitions:
        if "FAT" in p.desc.upper():
            fat_partition = p
            break

    if fat_partition:
        print("\n[*] Lazy Tree Engine başlatılıyor...")
        lazy_engine = LazyTreeEngine(img, fat_partition.start)

        root_nodes = lazy_engine.list_directory()

        print("\n=== ROOT LAZY TREE ===")
        for node in root_nodes[:20]:  # ilk 20 göster
            prefix = "📁" if node.is_dir else "📄"
            print(f"{prefix} {node.name} (inode={node.inode})")

    print("\nCase Path:", case_path)
