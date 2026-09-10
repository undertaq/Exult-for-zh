from .catalog import load_catalog
import sys
if __name__ == '__main__':
    for entry in load_catalog(__import__('pathlib').Path(sys.argv[1])): print(entry.key, entry.source)
