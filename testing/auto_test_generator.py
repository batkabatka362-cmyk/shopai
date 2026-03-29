"""Automatic test case generation for engine inputs."""

import random
import string
import copy
import time
from typing import Any, Optional


class AutoTestGenerator:
    """Generate test cases, edge cases, and variations for engine testing."""

    def generate_test_cases(self, engine_name: str, input_schema: dict, count: int = 10) -> list[dict]:
        """Generate random valid test cases conforming to input_schema.

        Args:
            engine_name: Name of the target engine.
            input_schema: Dict mapping field names to field specs.
                Each spec is either a type string (e.g. "str") or a dict with
                'type' and optional 'constraints' (min, max, min_length, max_length, choices).
            count: Number of test cases to generate.

        Returns:
            List of test case dicts, each with 'input' and metadata.
        """
        cases = []
        for i in range(count):
            data = {}
            for field, spec in input_schema.items():
                if isinstance(spec, str):
                    field_type = spec
                    constraints = {}
                else:
                    field_type = spec.get("type", "str")
                    constraints = spec.get("constraints", {})
                data[field] = self._random_value_for_type(field_type, constraints)
            cases.append({
                "id": f"{engine_name}_test_{i}",
                "engine_name": engine_name,
                "input": data,
                "generated_at": time.time(),
                "kind": "random",
            })
        return cases

    def generate_edge_cases(self, engine_name: str, input_schema: dict) -> list[dict]:
        """Generate edge-case inputs: empty, null-like, large, unicode, boundary values, etc."""
        edge_cases = []
        case_id = 0

        def _add(desc: str, data: dict):
            nonlocal case_id
            edge_cases.append({
                "id": f"{engine_name}_edge_{case_id}",
                "engine_name": engine_name,
                "input": data,
                "edge_type": desc,
                "generated_at": time.time(),
                "kind": "edge",
            })
            case_id += 1

        # All fields empty / zero / None
        _add("all_empty", {f: self._empty_for_type(self._extract_type(spec)) for f, spec in input_schema.items()})
        _add("all_none", {f: None for f in input_schema})

        # Each field individually set to None
        for field in input_schema:
            base = {f: self._random_value_for_type(self._extract_type(s)) for f, s in input_schema.items()}
            base[field] = None
            _add(f"null_{field}", base)

        # Large values
        large = {}
        for field, spec in input_schema.items():
            ftype = self._extract_type(spec)
            if ftype in ("str", "string"):
                large[field] = "x" * 10000
            elif ftype in ("int", "integer"):
                large[field] = 2**31 - 1
            elif ftype in ("float", "number"):
                large[field] = 1e308
            elif ftype in ("list", "array"):
                large[field] = list(range(1000))
            else:
                large[field] = self._random_value_for_type(ftype)
        _add("large_values", large)

        # Unicode / special characters
        unicode_data = {}
        for field, spec in input_schema.items():
            ftype = self._extract_type(spec)
            if ftype in ("str", "string"):
                unicode_data[field] = "こんにちは 🚀 émojis & spëcîal <chars> \"quotes\" \\ /"
            else:
                unicode_data[field] = self._random_value_for_type(ftype)
        _add("unicode_special", unicode_data)

        # Empty string for all string fields
        empty_str = {}
        for field, spec in input_schema.items():
            ftype = self._extract_type(spec)
            empty_str[field] = "" if ftype in ("str", "string") else self._random_value_for_type(ftype)
        _add("empty_strings", empty_str)

        # Missing fields (empty dict)
        _add("missing_all_fields", {})

        return edge_cases

    def generate_from_examples(self, examples: list[dict], count: int = 5) -> list[dict]:
        """Generate variations of real example data by applying small random mutations."""
        if not examples:
            return []
        variations = []
        for i in range(count):
            base = copy.deepcopy(random.choice(examples))
            mutated = self._mutate(base)
            variations.append({
                "id": f"variation_{i}",
                "input": mutated,
                "generated_at": time.time(),
                "kind": "variation",
                "source_example_keys": sorted(base.keys()),
            })
        return variations

    def _random_value_for_type(self, field_type: str, constraints: Optional[dict] = None) -> Any:
        """Generate a random value for a given type string."""
        constraints = constraints or {}
        ft = field_type.lower()

        if ft in ("str", "string"):
            choices = constraints.get("choices")
            if choices:
                return random.choice(choices)
            min_len = constraints.get("min_length", 3)
            max_len = constraints.get("max_length", 20)
            length = random.randint(min_len, max_len)
            return "".join(random.choices(string.ascii_lowercase + string.digits, k=length))

        if ft in ("int", "integer"):
            lo = constraints.get("min", 0)
            hi = constraints.get("max", 1000)
            return random.randint(int(lo), int(hi))

        if ft in ("float", "number"):
            lo = constraints.get("min", 0.0)
            hi = constraints.get("max", 1000.0)
            return round(random.uniform(float(lo), float(hi)), 4)

        if ft in ("bool", "boolean"):
            return random.choice([True, False])

        if ft in ("list", "array"):
            length = random.randint(1, 5)
            return [random.randint(0, 100) for _ in range(length)]

        if ft in ("dict", "object"):
            return {"key": self._random_value_for_type("str"), "value": random.randint(0, 100)}

        return None

    def _mutate(self, example: dict) -> dict:
        """Apply small random changes to an example dict."""
        mutated = copy.deepcopy(example)
        if not mutated:
            return mutated

        keys = list(mutated.keys())
        num_mutations = max(1, len(keys) // 3)
        fields_to_mutate = random.sample(keys, min(num_mutations, len(keys)))

        for field in fields_to_mutate:
            value = mutated[field]
            if isinstance(value, str):
                if len(value) > 1:
                    idx = random.randint(0, len(value) - 1)
                    char = random.choice(string.ascii_lowercase)
                    mutated[field] = value[:idx] + char + value[idx + 1:]
                else:
                    mutated[field] = value + random.choice(string.ascii_lowercase)
            elif isinstance(value, int):
                delta = random.randint(-10, 10)
                mutated[field] = value + delta
            elif isinstance(value, float):
                delta = random.uniform(-1.0, 1.0)
                mutated[field] = round(value + delta, 4)
            elif isinstance(value, bool):
                mutated[field] = not value
            elif isinstance(value, list) and value:
                idx = random.randint(0, len(value) - 1)
                if isinstance(value[idx], (int, float)):
                    mutated[field][idx] = value[idx] + random.randint(-5, 5)
            elif isinstance(value, dict):
                mutated[field] = self._mutate(value)
        return mutated

    @staticmethod
    def _extract_type(spec) -> str:
        if isinstance(spec, str):
            return spec
        if isinstance(spec, dict):
            return spec.get("type", "str")
        return "str"

    @staticmethod
    def _empty_for_type(field_type: str) -> Any:
        ft = field_type.lower()
        if ft in ("str", "string"):
            return ""
        if ft in ("int", "integer"):
            return 0
        if ft in ("float", "number"):
            return 0.0
        if ft in ("bool", "boolean"):
            return False
        if ft in ("list", "array"):
            return []
        if ft in ("dict", "object"):
            return {}
        return None
