"""The baseline plus one real sample of every BoM warning type, dates shifted to look current.

Files keep the names BoM gives them, so the tsunami sample is `IDY68027_cap.xml` (underscore).
Known gap, kept on purpose: `LIST *.cap.xml` does not list it, so the integration never sees a
tsunami warning. The samples overwrite the baseline files of the same name (IDQ21033, IDQ21013).
The shift uses the time the scenario is applied, so re-apply it to refresh the dates.
"""

from pathlib import Path

from .. import layout


def apply(root: Path) -> None:
    for sample in sorted(layout.CAP_SAMPLES.glob("ID*")):
        layout.put_sample(root, sample.name)
