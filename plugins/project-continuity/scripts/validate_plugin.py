from __future__ import annotations

import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path

import yaml
from PIL import Image

ALLOWED_CATEGORIES = {
    'Productivity', 'Creativity', 'Developer Tools', 'Business & Operations',
    'Data & Analytics', 'Communication', 'Education & Research', 'Security',
    'Finance', 'Healthcare', 'Travel', 'Entertainment', 'Other'
}

# Repo/runtime paths that are not part of the Skills-only plugin inventory.
PACKAGE_SKIP_NAMES = {'.git', '.continuity', '__pycache__'}
PACKAGE_SKIP_FILES = {'.gitignore', 'AGENTS.md', 'CONTINUITY.md', '.DS_Store'}

def fail(msg: str) -> None:
    raise AssertionError(msg)

def require(cond: bool, msg: str) -> None:
    if not cond:
        fail(msg)

def is_package_file(path: Path, root: Path) -> bool:
    rel = path.relative_to(root)
    if rel.name == 'MANIFEST.sha256' or path.suffix in {'.pyc', '.pyo'}:
        return False
    if any(part in PACKAGE_SKIP_NAMES for part in rel.parts):
        return False
    if rel.as_posix() in PACKAGE_SKIP_FILES:
        return False
    return True


def safe_relative_path(value: str, root: Path) -> Path:
    require(isinstance(value, str) and value.startswith('./'), f'Path must start with ./: {value!r}')
    rel = Path(value[2:])
    require(not rel.is_absolute() and '..' not in rel.parts, f'Unsafe path: {value}')
    target = (root / rel).resolve()
    require(root.resolve() in target.parents or target == root.resolve(), f'Path escapes plugin: {value}')
    return target

def contrast(hex_a: str, hex_b: str) -> float:
    def lum(h: str) -> float:
        h = h.lstrip('#')
        rgb = [int(h[i:i+2], 16) / 255 for i in (0, 2, 4)]
        vals = [c / 12.92 if c <= .03928 else ((c + .055) / 1.055) ** 2.4 for c in rgb]
        return .2126 * vals[0] + .7152 * vals[1] + .0722 * vals[2]
    a, b = lum(hex_a), lum(hex_b)
    hi, lo = max(a, b), min(a, b)
    return (hi + .05) / (lo + .05)

def validate(root: Path) -> list[str]:
    out: list[str] = []
    root = root.resolve()
    manifest_path = root / '.codex-plugin' / 'plugin.json'
    require(manifest_path.is_file(), 'Missing .codex-plugin/plugin.json')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))

    name = manifest.get('name')
    require(isinstance(name, str) and 1 <= len(name) <= 64, 'Invalid plugin name length')
    require(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', name) is not None, 'Invalid plugin name format')
    version = manifest.get('version')
    require(isinstance(version, str) and re.fullmatch(r'\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?', version), 'Invalid semantic version')
    description = manifest.get('description')
    require(isinstance(description, str) and 1 <= len(description) <= 1024, 'Invalid description')

    author = manifest.get('author')
    require(isinstance(author, dict) and isinstance(author.get('name'), str) and author['name'].strip(), 'author.name is required')
    require(len(author['name']) <= 120, 'author.name too long')
    require(manifest.get('license') == 'MIT', 'Expected MIT license')

    require('mcpServers' not in manifest, 'Skills-only plugin must not declare mcpServers')
    require('apps' not in manifest, 'Skills-only plugin must not declare apps')
    require(not (root / '.mcp.json').exists(), 'Skills-only plugin must not include .mcp.json')
    require(not (root / '.app.json').exists(), 'Skills-only plugin must not include .app.json')
    require(not (root / 'hooks').exists(), 'Skills-only v1.0.0 must not include lifecycle hooks')

    skills_path = manifest.get('skills')
    require(skills_path == './skills/', 'skills must point to ./skills/')
    skills_root = safe_relative_path(skills_path, root)
    require(skills_root.is_dir(), 'Missing skills directory')
    skill_dirs = sorted(p for p in skills_root.iterdir() if p.is_dir() and not p.name.startswith('.'))
    require(skill_dirs, 'At least one skill is required')

    seen_skill_names: set[str] = set()
    for skill_dir in skill_dirs:
        skill_file = skill_dir / 'SKILL.md'
        require(skill_file.is_file(), f'Missing {skill_dir.name}/SKILL.md')
        text = skill_file.read_text(encoding='utf-8')
        require(text.startswith('---\n'), f'{skill_file}: missing YAML frontmatter')
        end = text.find('\n---\n', 4)
        require(end > 4, f'{skill_file}: unclosed YAML frontmatter')
        fm = yaml.safe_load(text[4:end])
        require(isinstance(fm, dict), f'{skill_file}: invalid frontmatter')
        skill_name = fm.get('name')
        skill_description = fm.get('description')
        require(isinstance(skill_name, str) and skill_name.strip(), f'{skill_file}: name required')
        require(isinstance(skill_description, str) and 1 <= len(skill_description) <= 1024, f'{skill_file}: description invalid')
        require(skill_name not in seen_skill_names, f'Duplicate skill name: {skill_name}')
        seen_skill_names.add(skill_name)
        require(len(f'{name}:{skill_name}') <= 64, f'Combined plugin:skill identity too long: {name}:{skill_name}')
        require(text[end + 5:].strip(), f'{skill_file}: empty instructions')

        agent_file = skill_dir / 'agents' / 'openai.yaml'
        if agent_file.exists():
            agent = yaml.safe_load(agent_file.read_text(encoding='utf-8'))
            require(isinstance(agent, dict) and isinstance(agent.get('interface'), dict), 'agents/openai.yaml interface missing')
            interface = agent['interface']
            for key in ('display_name', 'short_description'):
                require(isinstance(interface.get(key), str) and interface[key].strip(), f'agents/openai.yaml {key} missing')
            policy = agent.get('policy', {})
            require(isinstance(policy, dict), 'agents/openai.yaml policy must be a mapping')
            products = policy.get('products', [])
            require(set(products).issubset({'CHAT', 'CODEX'}) and products, 'agents/openai.yaml products invalid')
            require(isinstance(policy.get('allow_implicit_invocation'), bool), 'allow_implicit_invocation must be boolean')

    interface = manifest.get('interface')
    require(isinstance(interface, dict), 'interface object required')
    display = interface.get('displayName')
    short = interface.get('shortDescription')
    long_desc = interface.get('longDescription')
    developer = interface.get('developerName')
    require(isinstance(display, str) and 1 <= len(display) <= 30 and '\n' not in display, 'displayName invalid for directory')
    require(isinstance(short, str) and 1 <= len(short) <= 30 and '\n' not in short, 'shortDescription invalid for directory')
    require(isinstance(long_desc, str) and 1 <= len(long_desc) <= 4000, 'longDescription invalid')
    require(isinstance(developer, str) and 1 <= len(developer) <= 80 and '\n' not in developer, 'developerName invalid')
    require(developer == author['name'], 'author.name and interface.developerName must match')
    require(interface.get('category') in ALLOWED_CATEGORIES, 'Unknown category')

    capabilities = interface.get('capabilities')
    require(isinstance(capabilities, list) and 1 <= len(capabilities) <= 20, 'capabilities invalid')
    for cap in capabilities:
        require(isinstance(cap, str) and 1 <= len(cap) <= 120 and '\n' not in cap, 'capability invalid')

    prompts = interface.get('defaultPrompt')
    require(isinstance(prompts, list) and 1 <= len(prompts) <= 3, 'defaultPrompt invalid')
    normalized: set[str] = set()
    for prompt in prompts:
        require(isinstance(prompt, str) and 1 <= len(prompt) <= 128 and '\n' not in prompt, 'starter prompt invalid')
        require('@' not in prompt, 'starter prompt must not contain app mention')
        norm = ' '.join(prompt.split()).casefold()
        require(norm not in normalized, 'starter prompts must be unique')
        normalized.add(norm)

    value = interface.get('brandColor')
    require(isinstance(value, str) and re.fullmatch(r'#[0-9A-Fa-f]{6}', value), 'brandColor invalid')
    require(contrast(value, '#FFFFFF') >= 2.0, 'brandColor contrast against white is below 2:1')

    require('screenshots' not in interface, 'Skills-only plugin must not declare screenshots')
    for key in ('logo', 'composerIcon'):
        target = safe_relative_path(interface.get(key), root)
        require(target.is_file(), f'{key} file missing')
        require(target.stat().st_size <= 5 * 1024 * 1024, f'{key} exceeds 5 MiB')
        with Image.open(target) as image:
            require(image.width == image.height, f'{key} must be square')
            require(48 <= image.width <= 4096, f'{key} dimensions out of range')

    manifest_hash_path = root / 'MANIFEST.sha256'
    require(manifest_hash_path.is_file(), 'Missing plugin MANIFEST.sha256')
    manifest_lines = [line for line in manifest_hash_path.read_text(encoding='utf-8').splitlines() if line.strip()]
    declared = {}
    for line in manifest_lines:
        digest, rel = line.split('  ', 1)
        require(re.fullmatch(r'[0-9a-f]{64}', digest) is not None, f'Invalid manifest digest: {line}')
        require(rel not in declared, f'Duplicate manifest entry: {rel}')
        declared[rel] = digest
    actual_files = sorted(
        p for p in root.rglob('*')
        if p.is_file() and is_package_file(p, root)
    )
    actual_rel = {p.relative_to(root).as_posix() for p in actual_files}
    require(set(declared) == actual_rel, 'MANIFEST.sha256 file set does not match package')
    for p in actual_files:
        rel = p.relative_to(root).as_posix()
        digest = hashlib.sha256(p.read_bytes()).hexdigest()
        require(declared[rel] == digest, f'MANIFEST.sha256 mismatch: {rel}')

    out.extend([
        'plugin manifest valid',
        f'{len(skill_dirs)} bundled skill(s) valid',
        'skills-only exclusions valid',
        'directory metadata valid',
        'branding assets valid',
        'plugin content manifest valid'
    ])
    return out

if __name__ == '__main__':
    root = Path(sys.argv[1] if len(sys.argv) > 1 else '.')
    try:
        checks = validate(root)
    except Exception as exc:
        print(f'FAIL: {exc}', file=sys.stderr)
        raise SystemExit(1)
    print('PASS')
    for check in checks:
        print(f'- {check}')
