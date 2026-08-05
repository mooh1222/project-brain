from collections.abc import Mapping


def direct_coverage(*objects: Mapping[str, object]) -> dict[str, object]:
    return {
        "version": 1,
        "mode": "direct",
        "objects": sorted(
            (
                {"id": str(obj["id"]), "kind": str(obj["kind"])}
                for obj in objects
            ),
            key=lambda item: (item["id"], item["kind"]),
        ),
    }
