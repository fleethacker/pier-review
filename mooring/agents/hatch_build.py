"""Bundle the canonical modeling contract in source and wheel distributions."""

from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class ContractBuildHook(BuildHookInterface):
    def initialize(self, version, build_data):
        destination = "mooring_agents/physics/modeling.openapi.yaml"
        root = Path(self.root)
        if (root / destination).is_file():
            # Wheels built from an sdist already have the bundled contract.
            return
        contract = root.parent / "contract" / "modeling.openapi.yaml"
        if not contract.is_file():
            raise FileNotFoundError(f"Modeling contract is missing: {contract}")
        build_data["force_include"][str(contract)] = destination
