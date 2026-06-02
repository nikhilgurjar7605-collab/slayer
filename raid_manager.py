# raid_manager.py
import asyncio
import random
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import logging

logger = logging.getLogger(__name__)

class RaidBoss:
    def __init__(self, clan_id: str, creator_id: int, name: str, level: int, hp_multiplier: float = 1.0):
        self.clan_id = clan_id
        self.creator_id = creator_id
        self.name = name
        self.level = level
        self.max_hp = int(5000 * level * hp_multiplier)  # Base HP scaled by level and player count
        self.current_hp = self.max_hp
        self.start_time: Optional[datetime] = None
        self.end_time: Optional[datetime] = None
        self.duration_minutes: int = 0
        self.participants: Dict[int, dict] = {}  # user_id -> {damage, joined_at, defeated}
        self.is_active = False
        self.is_completed = False
        self.reward_pool: List[dict] = []

    def add_participant(self, user_id: int, username: str):
        if user_id not in self.participants:
            self.participants[user_id] = {
                "username": username,
                "damage": 0,
                "joined_at": datetime.now(),
                "defeated": False,
                "attempts": 0
            }

    def deal_damage(self, user_id: int, damage: int):
        if user_id in self.participants:
            self.participants[user_id]["damage"] += damage
            self.current_hp -= damage
            if self.current_hp < 0:
                self.current_hp = 0
            return True
        return False

    def mark_defeated(self, user_id: int):
        if user_id in self.participants:
            self.participants[user_id]["defeated"] = True
            self.participants[user_id]["attempts"] += 1

    def get_leaderboard(self):
        sorted_users = sorted(
            self.participants.items(),
            key=lambda x: x[1]["damage"],
            reverse=True
        )
        return sorted_users

    def is_expired(self):
        if self.end_time and datetime.now() > self.end_time:
            return True
        return False

    def time_remaining(self):
        if self.end_time:
            remaining = self.end_time - datetime.now()
            if remaining.total_seconds() <= 0:
                return "00:00"
            minutes = int(remaining.total_seconds() // 60)
            seconds = int(remaining.total_seconds() % 60)
            return f"{minutes:02d}:{seconds:02d}"
        return "Unknown"


class RaidManager:
    def __init__(self):
        self.active_raids: Dict[str, RaidBoss] = {}  # clan_id -> RaidBoss
        self.join_timers: Dict[str, asyncio.Task] = {}
        self.lock = asyncio.Lock()

    async def create_raid(self, clan_id: str, creator_id: int, creator_name: str, duration_min: int, boss_name: str, level: int, player_count: int):
        async with self.lock:
            if clan_id in self.active_raids:
                return False, "A raid is already active for this clan."

            # Scale boss HP based on number of potential participants (simplified estimate)
            hp_multiplier = 1.0 + (player_count * 0.2) 
            
            boss = RaidBoss(clan_id, creator_id, boss_name, level, hp_multiplier)
            boss.duration_minutes = duration_min
            boss.start_time = datetime.now()
            boss.end_time = boss.start_time + timedelta(minutes=duration_min)
            boss.is_active = True

            self.active_raids[clan_id] = boss

            # Start the auto-end timer
            task = asyncio.create_task(self._raid_timer(clan_id, duration_min))
            self.join_timers[clan_id] = task

            return True, f"Raid started! Boss: {boss_name} (HP: {boss.max_hp:,}). Duration: {duration_min} mins."

    async def _raid_timer(self, clan_id: str, duration: int):
        await asyncio.sleep(duration * 60)
        async with self.lock:
            if clan_id in self.active_raids:
                raid = self.active_raids[clan_id]
                if not raid.is_completed:
                    await self.end_raid(clan_id, reason="time_expired")

    async def join_raid(self, clan_id: str, user_id: int, username: str):
        async with self.lock:
            if clan_id not in self.active_raids:
                return False, "No active raid found."
            
            raid = self.active_raids[clan_id]
            if raid.is_completed or raid.is_expired():
                return False, "This raid has already ended."

            raid.add_participant(user_id, username)
            return True, f"You joined the raid against {raid.name}!"

    async def leave_raid(self, clan_id: str, user_id: int):
        # Optional: Implement leave logic if needed before defeat
        pass

    async def report_damage(self, clan_id: str, user_id: int, damage: int):
        async with self.lock:
            if clan_id not in self.active_raids:
                return False, "Raid not found."
            raid = self.active_raids[clan_id]
            if raid.is_completed:
                return False, "Raid already completed."
            
            raid.deal_damage(user_id, damage)
            
            boss_defeated = False
            if raid.current_hp <= 0:
                raid.is_completed = True
                boss_defeated = True
                # Cancel the timer
                if clan_id in self.join_timers:
                    self.join_timers[clan_id].cancel()
            
            return boss_defeated, f"Dealt {damage:,} damage! Boss HP: {raid.current_hp:,}/{raid.max_hp:,}"

    async def end_raid(self, clan_id: str, reason: str = "manual"):
        async with self.lock:
            if clan_id not in self.active_raids:
                return
            
            raid = self.active_raids[clan_id]
            raid.is_active = False
            raid.is_completed = True
            
            # Calculate rewards and generate report
            leaderboard = raid.get_leaderboard()
            
            # Clean up
            if clan_id in self.join_timers:
                del self.join_timers[clan_id]
            del self.active_raids[clan_id]
            
            return raid, leaderboard

    def get_raid_status(self, clan_id: str):
        if clan_id not in self.active_raids:
            return None
        raid = self.active_raids[clan_id]
        return {
            "name": raid.name,
            "hp": f"{raid.current_hp:,}/{raid.max_hp:,}",
            "time_left": raid.time_remaining(),
            "participants": len(raid.participants),
            "is_active": raid.is_active and not raid.is_expired()
        }

# Global instance
raid_manager = RaidManager()
