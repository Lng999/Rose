#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Repository Downloader
Syncs the skin library from LeagueSkins' manifest (utils.download.skin_sync):
only the files that differ are downloaded, from raw.githubusercontent.com, with
no GitHub API call.
"""

import os
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple
from utils.core.logging import get_logger
from utils.core.paths import get_classic_skins_dir, get_skins_dir, get_user_data_dir
from utils.core.safe_extract import is_safe_path

log = get_logger()

ProgressCallback = Callable[[int, Optional[str]], None]


def _listing(folder) -> List[os.DirEntry]:
    """The entries of *folder*, none when it cannot be listed."""
    try:
        with os.scandir(folder) as entries:
            return list(entries)
    except OSError:
        return []


def _is_id(name: str) -> bool:
    try:
        int(name)
        return True
    except ValueError:
        return False


def _id_files(skin_id: str, entries: List[os.DirEntry]) -> Tuple[bool, bool]:
    """Whether a skin's or chroma's folder holds its archive, and its preview."""
    names = {os.path.normcase(entry.name) for entry in entries}
    has_archive = any(os.path.normcase(f"{skin_id}{ext}") in names for ext in (".zip", ".fantome"))
    return has_archive, os.path.normcase(f"{skin_id}.png") in names


class RepoDownloader:
    """Keeps the local skin library (skins/, classic/ and resources/) in sync with LeagueSkins"""
    
    def __init__(
        self,
        target_dir: Path = None,
        progress_callback: Optional[ProgressCallback] = None,
    ):
        # Use user data directory for skins to avoid permission issues
        self.target_dir = target_dir or get_skins_dir()
        self.progress_callback = progress_callback

        # Rift Classic skins (the repository's classic/ folder) and the resources
        # folder sit next to the skins (a library given its own folder keeps them there)
        self.classic_dir = get_classic_skins_dir() if target_dir is None else self.target_dir.parent / "classic"
        self.resources_dir = (get_user_data_dir() if target_dir is None else self.target_dir.parent) / "resources"
    
    def _emit_progress(self, percent: float, message: Optional[str] = None):
        if not self.progress_callback:
            return
        bounded = max(0.0, min(percent, 100.0))
        self.progress_callback(int(bounded), message)

    def _resolve_local_path(self, repo_path: str) -> Optional[Path]:
        """Map a repo-relative path (skins/..., classic/... or resources/...) to a local path."""
        if repo_path.startswith('skins/'):
            base_dir, relative = self.target_dir, repo_path[len('skins/'):]
        elif repo_path.startswith('classic/'):
            base_dir, relative = self.classic_dir, repo_path[len('classic/'):]
        elif repo_path.startswith('resources/'):
            base_dir, relative = self.resources_dir, repo_path[len('resources/'):]
        else:
            return None
        local_path = base_dir / relative
        if not is_safe_path(base_dir, local_path):
            log.warning(f"Skipping repository path outside the target folder: {repo_path}")
            return None
        return local_path

    def sync_from_manifest(self) -> Optional[bool]:
        """Sync the library from LeagueSkins' manifest (utils.download.skin_sync).

        None when no listing could be read; else whether every file is in place
        (a sync GitHub throttled resumes at the next start).
        """
        from utils.download.skin_sync import SkinSync

        sync = SkinSync(
            resolve=self._resolve_local_path,
            roots=[self.target_dir, self.classic_dir, self.resources_dir],
            state_dir=self.target_dir,
            progress=self._emit_progress,
        )
        result = sync.run()
        return None if result is None else result.complete

    def download_incremental_updates(self, force_update: bool = False) -> bool:
        """Sync the library from the manifest (a missing library is downloaded
        the same way). False when it could not be read: the library stays as it is."""
        try:
            synced = self.sync_from_manifest()
            if synced is None:
                log.warning("No skin listing available - the skin library is left as it is")
                self._emit_progress(100, "Skin update unavailable")
                return False
            return synced
        except Exception as e:
            log.error(f"Failed to check for updates: {e}")
            self._emit_progress(100, f"Failed: {e}")
            return False
    
    def get_skin_stats(self) -> dict:
        """Get statistics about downloaded skins (total IDs per champion)"""
        if not self.target_dir.exists():
            return {}
        
        stats = {}
        for champion_dir in self.target_dir.iterdir():
            if champion_dir.is_dir():
                skin_files = list(champion_dir.glob("*.zip")) + list(champion_dir.glob("*.fantome"))
                stats[champion_dir.name] = len(skin_files)

        return stats
    
    def get_detailed_stats(self) -> Dict[str, int]:
        """
        Get detailed statistics categorizing base skins and chromas from new merged format
        
        Structure:
        - Base skin: {champion_id}/{skin_id}/{skin_id}.zip and {skin_id}.png
        - Chroma: {champion_id}/{skin_id}/{chroma_id}/{chroma_id}.zip and {chroma_id}.png
        
        Returns:
            Dict with keys: 'total_skins', 'total_chromas', 'total_ids', 'total_previews'
        """
        total_skins = 0  # Base skins only (zip files in skin subdirectories)
        total_chromas = 0  # Chromas only (zip files in chroma subdirectories)
        total_previews = 0  # All preview images (png files)

        # One listing per folder, instead of three exists() calls per skin and
        # chroma: this runs twice per start, and took 1.9 s each time over a
        # library of 9,000 skins and chromas
        for champion_dir in _listing(self.target_dir):
            if not champion_dir.is_dir():
                continue

            # Count skins and chromas in skin subdirectories
            # Structure: {champion_id}/{skin_id}/{skin_id}.zip and {skin_id}.png
            for skin_dir in _listing(champion_dir.path):
                if not skin_dir.is_dir() or not _is_id(skin_dir.name):
                    continue
                skin_entries = _listing(skin_dir.path)
                has_archive, has_preview = _id_files(skin_dir.name, skin_entries)
                total_skins += has_archive
                total_previews += has_preview

                # Count chromas in this skin's chroma subdirectories
                # Structure: {champion_id}/{skin_id}/{chroma_id}/{chroma_id}.zip or .fantome
                for chroma_dir in skin_entries:
                    if not chroma_dir.is_dir() or not _is_id(chroma_dir.name):
                        continue
                    has_archive, has_preview = _id_files(chroma_dir.name, _listing(chroma_dir.path))
                    total_chromas += has_archive
                    total_previews += has_preview

        return {
            'total_skins': total_skins,
            'total_chromas': total_chromas,
            'total_ids': total_skins + total_chromas,
            'total_previews': total_previews
        }


def download_skins_from_repo(
    target_dir: Path = None,
    force_update: bool = False,
    tray_manager=None,
    use_incremental: bool = True,
    progress_callback: Optional[ProgressCallback] = None,
) -> bool:
    """Download skins from repository with optional incremental updates"""
    try:
        # Note: tray_manager status is already set by caller (download_skins_on_startup)
        downloader = RepoDownloader(target_dir, progress_callback=progress_callback)
        
        # Get current detailed stats
        current_detailed = downloader.get_detailed_stats()
        
        if current_detailed['total_ids'] > 0:
            log.info(f"Found {current_detailed['total_skins']} base skins + "
                    f"{current_detailed['total_chromas']} chromas = "
                    f"{current_detailed['total_ids']} total skin IDs + "
                    f"{current_detailed['total_previews']} preview images")
        
        # The manifest sync downloads what differs, a missing library included
        success = downloader.download_incremental_updates(force_update)
        
        if success:
            # Get updated detailed stats
            final_detailed = downloader.get_detailed_stats()
            new_ids = final_detailed['total_ids'] - current_detailed['total_ids']
            new_previews = final_detailed['total_previews'] - current_detailed['total_previews']
            
            if new_ids > 0 or new_previews > 0:
                log.info(f"Downloaded {new_ids} new skin IDs and {new_previews} new preview images")
                log.info(f"Final totals: {final_detailed['total_skins']} base skins + "
                        f"{final_detailed['total_chromas']} chromas = "
                        f"{final_detailed['total_ids']} total skin IDs + "
                        f"{final_detailed['total_previews']} preview images")
            else:
                log.info("No new skins or previews to download")
            
            log.info("Skin library sync complete (skins + previews)")
        
        return success
        
    except Exception as e:
        log.error(f"Repository download failed: {e}")
        return False
