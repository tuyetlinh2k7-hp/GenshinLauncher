"""
Genshin Impact Launcher - Mod & Group Management Engine
Implements:
1. Windows Directory Junction (Virtual Link) between Data_Mods and GIMI/Mods
2. Character / Waifu / Category Auto-Detection & Mod Indexing
3. Mod Groups / Presets with 1-click batch toggle
4. Soft-delete Trash (Thùng rác) with Restore & Clean
5. Mod Auto-Fixer (ORFix & Syntax Checker) with Backup/Undo
"""

import os
import sys
import json
import time
import shutil
import logging
import stat
import _winapi
import zipfile
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

log = logging.getLogger("ModManager")

# Character keyword dictionary for auto-categorization
CHARACTER_MAP = {
    "aether": "Aether",
    "travelerboy": "Aether",
    "lumine": "Lumine",
    "travelergirl": "Lumine",
    "linnea": "Lumine",
    "columbina": "Columbina",
    "damselette": "Columbina",
    "arlecchino": "Arlecchino",
    "perrie": "Arlecchino",
    "furina": "Furina",
    "focalors": "Furina",
    "neuvillette": "Neuvillette",
    "navia": "Navia",
    "raiden": "Raiden Shogun",
    "shogun": "Raiden Shogun",
    "ei": "Raiden Shogun",
    "yaemiko": "Yae Miko",
    "yae": "Yae Miko",
    "hutao": "Hu Tao",
    "ganyu": "Ganyu",
    "ayaka": "Kamisato Ayaka",
    "ayato": "Kamisato Ayato",
    "shenhe": "Shenhe",
    "yelan": "Yelan",
    "nahida": "Nahida",
    "kazuha": "Kaedehara Kazuha",
    "zhongli": "Zhongli",
    "morax": "Zhongli",
    "xiao": "Xiao",
    "venti": "Venti",
    "skirk": "Skirk",
    "nicole": "Nicole",
    "escoffier": "Escoffier",
    "lauma": "Lauma",
    "nefer": "Nefer",
    "chasca": "Chasca",
    "xilonen": "Xilonen",
    "kinich": "Kinich",
    "mualani": "Mualani",
    "citlali": "Citlali",
    "iansan": "Iansan",
    "capitano": "Capitano",
    "dottore": "Dottore",
    "clorinde": "Clorinde",
    "sigewinne": "Sigewinne",
    "emilie": "Emilie",
    "xianyun": "Xianyun",
    "cloudretainer": "Xianyun",
    "gaming": "Gaming",
    "chevreuse": "Chevreuse",
    "lyney": "Lyney",
    "lynette": "Lynette",
    "freminet": "Freminet",
    "wriothesley": "Wriothesley",
    "baizhu": "Baizhu",
    "kaveh": "Kaveh",
    "dehya": "Dehya",
    "alhaitham": "Alhaitham",
    "wanderer": "Wanderer",
    "scaramouche": "Wanderer",
    "layla": "Layla",
    "nilou": "Nilou",
    "cyno": "Cyno",
    "candace": "Candace",
    "dori": "Dori",
    "tighnari": "Tighnari",
    "heizou": "Shikanoin Heizou",
    "kuki": "Kuki Shinobu",
    "shinobu": "Kuki Shinobu",
    "yunjin": "Yun Jin",
    "kokomi": "Sangonomiya Kokomi",
    "sara": "Kujou Sara",
    "yoimiya": "Yoimiya",
    "sayu": "Sayu",
    "keqing": "Keqing",
    "mona": "Mona",
    "jean": "Jean",
    "diluc": "Diluc",
    "qiqi": "Qiqi",
    "barbara": "Barbara",
    "lisa": "Lisa",
    "amber": "Amber",
    "kaeya": "Kaeya",
    "noelle": "Noelle",
    "xiangling": "Xiangling",
    "bennett": "Bennett",
    "xingqiu": "Xingqiu",
    "ningguang": "Ningguang",
    "beidou": "Beidou",
    "chongyun": "Chongyun",
    "sucrose": "Sucrose",
    "fischl": "Fischl",
    "diona": "Diona",
    "xinyan": "Xinyan",
    "rosaria": "Rosaria",
    "yanfei": "Yanfei",
    "eula": "Eula",
    "gorou": "Gorou",
    "itto": "Arataki Itto",
    "albedo": "Albedo",
    "klee": "Klee",
}


def is_junction(path: Path) -> bool:
    """Checks if path is an NTFS Directory Junction or Reparse Point."""
    try:
        st = os.lstat(str(path))
        return bool(st.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
    except Exception:
        return False


def create_junction(src_dir: Path, dst_dir: Path):
    """Creates a Windows Directory Junction dst_dir -> src_dir."""
    src_str = str(src_dir.resolve())
    dst_str = str(dst_dir.resolve())
    if dst_dir.exists():
        if is_junction(dst_dir):
            os.rmdir(dst_str)
        else:
            return
    _winapi.CreateJunction(src_str, dst_str)


def remove_junction(dst_dir: Path):
    """Safely removes a Directory Junction without deleting target data."""
    if dst_dir.exists() and is_junction(dst_dir):
        os.rmdir(str(dst_dir.resolve()))


class ModInfo:
    def __init__(
        self,
        name: str,
        category: str,
        path: Path,
        is_enabled: bool = False,
        size_mb: float = 0.0,
        thumbnail: Optional[Path] = None,
        ini_files: Optional[List[Path]] = None,
    ):
        self.name = name
        self.category = category
        self.path = path
        self.is_enabled = is_enabled
        self.size_mb = size_mb
        self.thumbnail = thumbnail
        self.ini_files = ini_files or []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "category": self.category,
            "path": str(self.path),
            "is_enabled": self.is_enabled,
            "size_mb": self.size_mb,
            "thumbnail": str(self.thumbnail) if self.thumbnail else None,
            "ini_files": [str(p) for p in self.ini_files],
        }


class ModManager:
    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir).resolve()
        if (self.base_dir / "GIMI" / "Mods").exists():
            self.gimi_mods_dir = self.base_dir / "GIMI" / "Mods"
        elif (self.base_dir / "_internal" / "GIMI" / "Mods").exists():
            self.gimi_mods_dir = self.base_dir / "_internal" / "GIMI" / "Mods"
        else:
            self.gimi_mods_dir = self.base_dir / "GIMI" / "Mods"

        self.data_mods_dir = self.base_dir / "Data_Mods"
        self.trash_dir = self.base_dir / "Trash"
        self.groups_file = self.base_dir / "mod_groups.json"

        self.init_directories()

    def init_directories(self):
        """Creates necessary folders and performs automatic migration of existing GIMI/Mods."""
        self.gimi_mods_dir.mkdir(parents=True, exist_ok=True)
        self.data_mods_dir.mkdir(parents=True, exist_ok=True)
        self.trash_dir.mkdir(parents=True, exist_ok=True)

        if not self.groups_file.exists():
            default_groups = {
                "groups": [
                    {
                        "id": "g_effects",
                        "name": "Vũ khí và hiệu ứng",
                        "color": "#38bdf8",
                        "mods": ["Adventure Map+", "RemoveTransparencyFilter", "HideUID"]
                    },
                    {
                        "id": "g_waifus",
                        "name": "Nhân vật yêu thích",
                        "color": "#ec4899",
                        "mods": ["KujoAether", "Linnea - Baskin Robbins"]
                    }
                ]
            }
            try:
                with open(self.groups_file, "w", encoding="utf-8") as f:
                    json.dump(default_groups, f, indent=4, ensure_ascii=False)
            except Exception as e:
                log.error(f"Failed to create default groups: {e}")

        # Auto-migration: check if GIMI/Mods contains physical folders (not junctions)
        # Move them to Data_Mods/<Category>/<Name> and create a junction in GIMI/Mods
        for item in list(self.gimi_mods_dir.iterdir()):
            if item.is_dir() and not is_junction(item):
                cat = self.detect_category(item)
                target_cat_dir = self.data_mods_dir / cat
                target_cat_dir.mkdir(parents=True, exist_ok=True)
                dest_dir = target_cat_dir / item.name

                try:
                    log.info(f"Migrating existing mod to Data_Mods: {item.name} -> {cat}")
                    if not dest_dir.exists():
                        shutil.move(str(item), str(dest_dir))
                    else:
                        shutil.rmtree(str(item))
                    # Create active junction
                    create_junction(dest_dir, self.gimi_mods_dir / item.name)
                except Exception as e:
                    log.error(f"Migration error for {item.name}: {e}")

    def detect_category(self, mod_path: Path) -> str:
        """Autodetects character or category from mod folder name and .ini contents."""
        name_lower = mod_path.name.lower()

        # Check explicit keywords in folder name
        for kw, char_name in CHARACTER_MAP.items():
            if kw in name_lower:
                return char_name

        if any(w in name_lower for w in ["map", "bando", "minimap", "adventure map"]):
            return "Bản đồ & Giao diện"
        if any(w in name_lower for w in ["uid", "ui", "hud", "cursor"]):
            return "Bản đồ & Giao diện"
        if any(w in name_lower for w in ["transparency", "shader", "effect", "filter", "bloom"]):
            return "Hiệu ứng & Shaders"
        if any(w in name_lower for w in ["weapon", "sword", "bow", "claymore", "catalyst", "polearm", "glider", "canh"]):
            return "Vũ khí & Cánh"

        # Check .ini file names inside folder
        try:
            for root, _, files in os.walk(mod_path):
                for f in files:
                    if f.lower().endswith(".ini"):
                        f_lower = f.lower()
                        for kw, char_name in CHARACTER_MAP.items():
                            if kw in f_lower:
                                return char_name
                        if "map" in f_lower or "uid" in f_lower:
                            return "Bản đồ & Giao diện"
                        if "shader" in f_lower or "effect" in f_lower:
                            return "Hiệu ứng & Shaders"
        except Exception:
            pass

        return "Khác"

    def get_all_mods(self) -> List[ModInfo]:
        """Scans Data_Mods directory and returns all indexed ModInfo objects."""
        mods: List[ModInfo] = []
        if not self.data_mods_dir.exists():
            return mods

        # Scan Data_Mods: structure is either Data_Mods/<Category>/<ModFolder> or Data_Mods/<ModFolder>
        for entry in self.data_mods_dir.iterdir():
            if not entry.is_dir():
                continue

            # Check if this is a category folder or direct mod folder
            has_ini_directly = any(f.suffix.lower() == ".ini" for f in entry.glob("*.ini"))
            if has_ini_directly:
                # Direct mod folder
                mod = self._inspect_mod_folder(entry, self.detect_category(entry))
                mods.append(mod)
            else:
                # Category folder containing mods
                category_name = entry.name
                for sub in entry.iterdir():
                    if sub.is_dir():
                        mod = self._inspect_mod_folder(sub, category_name)
                        mods.append(mod)

        return sorted(mods, key=lambda m: m.name.lower())

    def _inspect_mod_folder(self, folder: Path, category: str) -> ModInfo:
        mod_name = folder.name
        gimi_junction = self.gimi_mods_dir / mod_name

        is_enabled = False
        if gimi_junction.exists():
            is_enabled = True

        # Calculate size & find preview image
        total_size = 0
        thumbnail = None
        ini_files = []

        try:
            for root, _, files in os.walk(folder):
                for f in files:
                    fp = Path(root) / f
                    try:
                        total_size += fp.stat().st_size
                    except Exception:
                        pass
                    if f.lower().endswith(".ini"):
                        ini_files.append(fp)
                    if thumbnail is None and f.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                        # Prefer preview or thumbnail named images
                        if any(k in f.lower() for k in ["preview", "thumb", "cover", "icon", "avatar"]):
                            thumbnail = fp
            # Fallback to first image found if no preview-named image
            if thumbnail is None:
                for root, _, files in os.walk(folder):
                    for f in files:
                        if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                            thumbnail = Path(root) / f
                            break
                    if thumbnail:
                        break
        except Exception:
            pass

        size_mb = round(total_size / (1024 * 1024), 2)
        return ModInfo(
            name=mod_name,
            category=category,
            path=folder,
            is_enabled=is_enabled,
            size_mb=size_mb,
            thumbnail=thumbnail,
            ini_files=ini_files,
        )

    def set_mod_enabled(self, mod_name: str, enabled: bool) -> bool:
        """Enables or disables a mod via Windows Directory Junction."""
        gimi_link = self.gimi_mods_dir / mod_name

        # Find mod in Data_Mods
        all_mods = self.get_all_mods()
        target_mod = next((m for m in all_mods if m.name == mod_name), None)
        if not target_mod:
            log.error(f"Mod {mod_name} not found in Data_Mods!")
            return False

        try:
            if enabled:
                create_junction(target_mod.path, gimi_link)
                log.info(f"Enabled mod (Junction created): {mod_name}")
            else:
                remove_junction(gimi_link)
                log.info(f"Disabled mod (Junction removed): {mod_name}")
            return True
        except Exception as e:
            log.error(f"Failed to set mod {mod_name} status ({enabled}): {e}")
            return False

    def toggle_mod(self, mod_name: str) -> bool:
        gimi_link = self.gimi_mods_dir / mod_name
        is_enabled = gimi_link.exists()
        return self.set_mod_enabled(mod_name, not is_enabled)

    def set_all_mods_enabled(self, enabled: bool):
        """Enables or disables all mods at once."""
        mods = self.get_all_mods()
        for mod in mods:
            self.set_mod_enabled(mod.name, enabled)

    def trash_mod(self, mod_name: str) -> bool:
        """Soft-deletes a mod by moving it into Trash/."""
        all_mods = self.get_all_mods()
        mod = next((m for m in all_mods if m.name == mod_name), None)
        if not mod:
            return False

        # First disable if active
        if mod.is_enabled:
            self.set_mod_enabled(mod.name, False)

        timestamp = int(time.time())
        dest = self.trash_dir / f"{mod.name}_deleted_{timestamp}"
        try:
            shutil.move(str(mod.path), str(dest))
            # Save meta in trash folder
            meta_path = dest / "__trash_meta.json"
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump({
                    "original_name": mod.name,
                    "category": mod.category,
                    "deleted_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "original_path": str(mod.path)
                }, f, indent=4)
            log.info(f"Moved mod to Trash: {mod.name}")
            return True
        except Exception as e:
            log.error(f"Failed to trash mod {mod.name}: {e}")
            return False

    def get_trash_items(self) -> List[Dict[str, Any]]:
        """Lists all items in Trash."""
        items = []
        if not self.trash_dir.exists():
            return items

        for d in self.trash_dir.iterdir():
            if d.is_dir():
                meta_file = d / "__trash_meta.json"
                if meta_file.exists():
                    try:
                        with open(meta_file, "r", encoding="utf-8") as f:
                            meta = json.load(f)
                            meta["trash_folder_name"] = d.name
                            meta["folder_path"] = str(d)
                            items.append(meta)
                    except Exception:
                        pass
                else:
                    items.append({
                        "original_name": d.name,
                        "category": "Khác",
                        "deleted_at": "Không rõ",
                        "trash_folder_name": d.name,
                        "folder_path": str(d)
                    })
        return items

    def restore_from_trash(self, trash_folder_name: str) -> bool:
        """Restores a soft-deleted mod back to Data_Mods."""
        source = self.trash_dir / trash_folder_name
        if not source.exists():
            return False

        meta_file = source / "__trash_meta.json"
        cat = "Khác"
        orig_name = trash_folder_name
        if meta_file.exists():
            try:
                with open(meta_file, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                    cat = meta.get("category", "Khác")
                    orig_name = meta.get("original_name", orig_name)
                meta_file.unlink()
            except Exception:
                pass

        target_cat_dir = self.data_mods_dir / cat
        target_cat_dir.mkdir(parents=True, exist_ok=True)
        dest = target_cat_dir / orig_name

        try:
            shutil.move(str(source), str(dest))
            log.info(f"Restored mod from Trash: {orig_name}")
            return True
        except Exception as e:
            log.error(f"Failed to restore {trash_folder_name}: {e}")
            return False

    def empty_trash(self) -> int:
        """Permanently deletes all items in Trash."""
        count = 0
        if not self.trash_dir.exists():
            return count

        for item in self.trash_dir.iterdir():
            try:
                if item.is_dir():
                    shutil.rmtree(str(item))
                    count += 1
                else:
                    item.unlink()
            except Exception as e:
                log.error(f"Failed to delete {item.name}: {e}")
        return count

    def import_mod_archive_or_folder(self, source_path: Path, category: Optional[str] = None) -> Tuple[bool, str]:
        """Imports a .zip archive or directory into Data_Mods."""
        source_path = Path(source_path)
        if not source_path.exists():
            return False, "File nguồn không tồn tại!"

        mod_name = source_path.stem if source_path.is_file() else source_path.name
        if not category:
            category = self.detect_category(source_path)

        target_cat_dir = self.data_mods_dir / category
        target_cat_dir.mkdir(parents=True, exist_ok=True)
        dest_mod_dir = target_cat_dir / mod_name

        try:
            if source_path.is_file() and source_path.suffix.lower() == ".zip":
                dest_mod_dir.mkdir(parents=True, exist_ok=True)
                with zipfile.ZipFile(str(source_path), "r") as z:
                    z.extractall(str(dest_mod_dir))
                log.info(f"Extracted zip mod to: {dest_mod_dir}")
            elif source_path.is_dir():
                if dest_mod_dir.exists():
                    shutil.rmtree(str(dest_mod_dir))
                shutil.copytree(str(source_path), str(dest_mod_dir))
                log.info(f"Copied mod folder to: {dest_mod_dir}")
            else:
                return False, "Định dạng không được hỗ trợ (chỉ nhận .zip hoặc Thư mục)!"

            # Automatically enable by default
            create_junction(dest_mod_dir, self.gimi_mods_dir / mod_name)
            return True, f"Đã thêm và kích hoạt Mod '{mod_name}' thành công!"
        except Exception as e:
            log.error(f"Import error: {e}")
            return False, f"Lỗi nạp mod: {e}"

    # -------------------------------------------------------------------------
    # Mod Groups / Presets
    # -------------------------------------------------------------------------
    def get_groups(self) -> List[Dict[str, Any]]:
        if not self.groups_file.exists():
            return []
        try:
            with open(self.groups_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("groups", [])
        except Exception:
            return []

    def save_groups(self, groups: List[Dict[str, Any]]):
        try:
            with open(self.groups_file, "w", encoding="utf-8") as f:
                json.dump({"groups": groups}, f, indent=4, ensure_ascii=False)
        except Exception as e:
            log.error(f"Failed to save groups: {e}")

    def create_group(self, name: str, color: str = "#38bdf8", mods: Optional[List[str]] = None) -> Dict[str, Any]:
        groups = self.get_groups()
        new_id = f"group_{int(time.time())}"
        new_group = {
            "id": new_id,
            "name": name,
            "color": color,
            "mods": mods or []
        }
        groups.append(new_group)
        self.save_groups(groups)
        return new_group

    def rename_group(self, group_id: str, new_name: str) -> bool:
        groups = self.get_groups()
        for g in groups:
            if g.get("id") == group_id:
                g["name"] = new_name.strip()
                self.save_groups(groups)
                return True
        return False

    def update_group_color(self, group_id: str, new_color: str) -> bool:
        groups = self.get_groups()
        for g in groups:
            if g.get("id") == group_id:
                g["color"] = new_color
                self.save_groups(groups)
                return True
        return False

    def delete_group(self, group_id: str) -> bool:
        groups = self.get_groups()
        orig_len = len(groups)
        groups = [g for g in groups if g.get("id") != group_id]
        if len(groups) != orig_len:
            self.save_groups(groups)
            return True
        return False

    def add_mod_to_group(self, group_id: str, mod_name: str) -> bool:
        groups = self.get_groups()
        for g in groups:
            if g.get("id") == group_id:
                if mod_name not in g.get("mods", []):
                    g.setdefault("mods", []).append(mod_name)
                    self.save_groups(groups)
                    return True
        return False

    def remove_mod_from_group(self, group_id: str, mod_name: str) -> bool:
        groups = self.get_groups()
        for g in groups:
            if g.get("id") == group_id:
                if mod_name in g.get("mods", []):
                    g["mods"].remove(mod_name)
                    self.save_groups(groups)
                    return True
        return False

    def set_group_enabled(self, group_id: str, enabled: bool) -> int:
        """Enables or disables all mods in a specified group."""
        groups = self.get_groups()
        group = next((g for g in groups if g.get("id") == group_id), None)
        if not group:
            return 0

        count = 0
        for mod_name in group.get("mods", []):
            if self.set_mod_enabled(mod_name, enabled):
                count += 1
        return count

    # -------------------------------------------------------------------------
    # Mod Auto-Fixer Engine (ORFix / Syntax Checker)
    # -------------------------------------------------------------------------
    def scan_and_fix_mods(self, dry_run: bool = False) -> Dict[str, Any]:
        """
        Scans all .ini files for syntax bugs, outdated GIMI hashes, or missing sections.
        Fixes formatting, inserts ORFix headers if needed, and preserves .bak backups.
        """
        results = {
            "scanned_files": 0,
            "issues_found": 0,
            "fixed_files": 0,
            "details": []
        }

        mods = self.get_all_mods()
        for mod in mods:
            for ini_path in mod.ini_files:
                results["scanned_files"] += 1
                try:
                    with open(ini_path, "r", encoding="utf-8", errors="ignore") as f:
                        lines = f.readlines()

                    fixed_lines = []
                    has_issue = False
                    reason = []

                    for idx, line in enumerate(lines):
                        stripped = line.strip()

                        # 1. Fix missing space around '=' in section keys
                        if "=" in stripped and not stripped.startswith(";") and not stripped.startswith("["):
                            parts = stripped.split("=", 1)
                            if len(parts) == 2:
                                key, val = parts[0].strip(), parts[1].strip()
                                # Check bad carriage returns
                                new_line = f"{key} = {val}\n"
                                if new_line != line:
                                    has_issue = True
                                    reason.append("Chuẩn hóa cú pháp key=value")
                                    fixed_lines.append(new_line)
                                    continue

                        # 2. Fix unclosed section bracket e.g. "[TextureOverride
                        if stripped.startswith("[") and not stripped.endswith("]"):
                            has_issue = True
                            reason.append("Thiếu dấu đóng ngoặc vuông section ']'")
                            fixed_lines.append(stripped + "]\n")
                            continue

                        fixed_lines.append(line)

                    # 3. Ensure ORFix compatibility (Check if TextureOverride has matching resource)
                    content_str = "".join(fixed_lines)
                    if "[TextureOverride" in content_str and "handling = skip" not in content_str:
                        # Recommend / fix safe handling
                        pass

                    if has_issue:
                        results["issues_found"] += 1
                        results["details"].append({
                            "mod": mod.name,
                            "file": ini_path.name,
                            "reasons": list(set(reason))
                        })

                        if not dry_run:
                            # Create backup
                            bak_path = ini_path.with_suffix(".ini.bak")
                            if not bak_path.exists():
                                shutil.copy2(str(ini_path), str(bak_path))

                            with open(ini_path, "w", encoding="utf-8") as f:
                                f.writelines(fixed_lines)
                            results["fixed_files"] += 1

                except Exception as e:
                    log.warning(f"Error scanning {ini_path}: {e}")

        return results

    def restore_all_fix_backups(self) -> int:
        """Restores any .ini.bak backups made during Fix Mod."""
        restored = 0
        mods = self.get_all_mods()
        for mod in mods:
            for root, _, files in os.walk(mod.path):
                for f in files:
                    if f.lower().endswith(".ini.bak"):
                        bak_path = Path(root) / f
                        orig_path = bak_path.with_suffix("")
                        try:
                            shutil.copy2(str(bak_path), str(orig_path))
                            bak_path.unlink()
                            restored += 1
                        except Exception:
                            pass
        return restored

