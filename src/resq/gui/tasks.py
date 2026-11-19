"""画面から別スレッドで実行する処理。各処理は自分専用に DB を開き直し、終わったら閉じる。

回復キーは引数として受け取るだけで、記録・保存しない（unlock 内で伏字処理される）。
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .. import catalog, deliver, diagnose, image, unlock
from ..cases import Case, get_case, open_workspace
from ..config import Workspace
from ..recover import compare, ingest, pipeline


@contextmanager
def opened(root: Path, case_id: str) -> Iterator[Case]:
    ws, db = open_workspace(Workspace(root))
    try:
        yield get_case(ws, db, case_id)
    finally:
        db.close()


def run_diagnose(root, case_id, source, symptoms, smart_json, device_id, stream) -> dict:
    with opened(root, case_id) as c:
        d = diagnose.diagnose(source, symptoms=symptoms, smart_json=Path(smart_json) if smart_json else None,
                              ctx=c.ctx)
        diagnose.save(d, c, device_id)
        return d.to_dict()


def run_image(root, case_id, source, accept_risk, retry, stream) -> int:
    with opened(root, case_id) as c:
        return image.acquire(c, source, accept_risk=accept_risk, retry_passes=retry, stream=stream)


def run_register(root, case_id, path, stream) -> int:
    with opened(root, case_id) as c:
        return image.register_existing(c, Path(path))


def run_recover(root, case_id, image_id, stages, use_testdisk, stream) -> dict:
    with opened(root, case_id) as c:
        return pipeline.run(c, image_id=image_id, stages=tuple(stages), use_testdisk=use_testdisk,
                            on_stage=lambda s: stream.write(f"  {s} を実行中…\n"))


def run_ingest(root, case_id, folder, engine, stream) -> dict:
    from ..recover import merge

    with opened(root, case_id) as c:
        ingest.ingest(c, Path(folder), engine=engine)
        return merge.merge(c)


def run_compare(root, case_id, a, b, stream) -> dict:
    with opened(root, case_id) as c:
        return compare.compare(c, a, b)


def run_catalog(root, case_id, stream) -> dict:
    with opened(root, case_id) as c:
        return catalog.build(c, pdf=True)


def run_deliver(root, case_id, target, operator, stream) -> dict:
    with opened(root, case_id) as c:
        return deliver.deliver(c, Path(target), operator=operator)


def run_unlock(root, case_id, image_id, key, kind, partition, stream) -> int:
    """解錠 → 復号済みイメージを取得 → 閉じる。key はこの関数の外に残さない。"""
    with opened(root, case_id) as c:
        if partition:
            image_id = unlock.extract_partition(c, image_id, *partition)
        dev = unlock.unlock(c, image_id, key, kind=kind)
        key = ""  # noqa: F841 - 参照を手放す
        try:
            return image.acquire(c, dev, accept_risk=True, stream=stream)
        finally:
            unlock.close(c, image_id)


def run_ios(root, case_id, udid, confirmed, stream) -> int:
    from ..mobile import ios
    from ..recover import merge

    with opened(root, case_id) as c:
        out = ios.backup(c, udid, confirmed)
        man = ios.extract_camera_roll(c, out, out.parent)
        merge.merge(c)
        return len(man.candidates)


def run_android(root, case_id, serial, confirmed, stream) -> int:
    from ..mobile import android
    from ..recover import merge

    with opened(root, case_id) as c:
        man = android.pull(c, serial, confirmed)
        merge.merge(c)
        return len(man.candidates)
