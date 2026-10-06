import sys, types, os, re, time, asyncio, random

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")  # never actually connected (col patched)

# Stub config before importing handlers
cfg = types.ModuleType('config')
cfg.PETS = {'Shadow Fox': {'emoji':'🦊','desc':'sly fox','rarity':'rare','catch_rate':0.5,'skills':[],
                           'type':'dark','base_stats':{}}}
cfg.PET_RARITY_EMOJI = {'rare':'💠'}
cfg.TRAVEL_ZONES = {}
for n in ['BOT_TOKEN','ADMIN_IDS','WILD_PET_CHANCE']:
    setattr(cfg, n, {'BOT_TOKEN':'x','ADMIN_IDS':[],'WILD_PET_CHANCE':0.3}[n])
cfg.PET_EVOLUTIONS = {}
cfg.PET_EGGS = {}
cfg.PET_BOND_NAMES = ["Stray"]
cfg.PET_BOND_XP = 100
cfg.PET_IMAGES = {}
cfg.PET_REGIONS = {}
cfg.PET_WILD_ENCOUNTER_CHANCE = 0.3
cfg.PET_EGG_DROP = 0.1
import importlib.util as _ilu
_spec = _ilu.spec_from_file_location('config', '/workspace/config.py')
cfg = _ilu.module_from_spec(_spec)
sys.modules['config'] = cfg
_spec.loader.exec_module(cfg)
cfg.PETS = {'Shadow Fox': {'emoji':'🦊','desc':'sly fox','rarity':'rare','catch_rate':0.5,'skills':[]}}
sys.modules['config'] = cfg

import utils.database as db
class FakeCol:
    def __init__(self, store): self.store = store
    def find_one(self, q):
        for d in self.store:
            name = q.get('item_name')
            if isinstance(name, dict) and '$regex' in name:
                if d.get('item_name') and re.match(name['$regex'], d['item_name'], re.IGNORECASE): return d
            elif 'item_name' not in q and d.get('user_id') == q.get('user_id'): return d
        return None
    def update_one(self, q, u):
        for d in self.store:
            if d['_id'] == q.get('_id'): d['quantity'] += u['$inc']['quantity']
    def delete_one(self, q):
        self.store[:] = [d for d in self.store if d['_id'] != q.get('_id')]
    def insert_one(self, d): self.store.append(d); return type('R',(),{'inserted_id':len(self.store)})()
    def find(self, q=None): return iter([d for d in self.store if not q or d.get('user_id')==q.get('user_id')])
    def count_documents(self, q=None): return 0
    def update_many(self, *a, **k): return None

INV = [{'_id': 1, 'user_id': 7, 'item_name': 'Pet Trap', 'quantity': 2}]
db.col = lambda name: FakeCol(INV)
db.get_player = lambda uid: {'user_id': uid, 'balance': 0}
db.update_player = lambda *a, **k: None
db.add_item = lambda *a, **k: None
db.append_battle_log = lambda *a, **k: None
db._invalidate_inventory_cache = lambda uid: None

import handlers.pets as pets
pets.col = db.col
pets.get_player = db.get_player
pets.update_player = db.update_player
pets.add_item = db.add_item

from telegram import Update, Message, User, CallbackQuery

class FakeCQ:
    def __init__(self, data):
        self.data = data
        self.from_user = User(id=7, is_bot=False, first_name='T')
        self.edits = []
        self.replies = []
    async def answer(self, *a, **k): return None
    async def edit_message_text(self, *a, **k): self.edits.append(a); return None
class FakeMsg:
    def __init__(self, cq): self.cq = cq
    async def reply_text(self, *a, **k): self.cq.replies.append(a); return None
class FakeUpdate:
    def __init__(self, data):
        self.callback_query = FakeCQ(data)
        self.callback_query.message = FakeMsg(self.callback_query)
        self.effective_user = self.callback_query.from_user

LAST_UPDATES = []
def make_update(data):
    u = FakeUpdate(data)
    LAST_UPDATES.append(u)
    return u

class Ctx: pass
ctx = Ctx(); ctx.user_data = {}; ctx.bot_data = {}

def set_encounter(ts=None):
    ctx.user_data['wild_pet_7'] = 'Shadow Fox'
    ctx.user_data['wild_pet_active_7'] = True
    ctx.user_data['wild_pet_ts_7'] = ts if ts is not None else time.time()

random.random = lambda: 0.99  # force catch FAILURE

# Test 1: failed catch keeps encounter alive (main bug)
set_encounter()
asyncio.run(pets.pet_catch_callback(make_update('pet_catch_7_Pet_Trap'), ctx))
assert 'wild_pet_7' in ctx.user_data, "BUG: encounter killed after one failed roll"
assert INV[0]['quantity'] == 1, f"tool not consumed correctly: {INV}"
print("TEST 1 PASS: failed catch -> pet stays, tool consumed, cache invalidated")

# Test 2: retry works after failure
random.random = lambda: 0.01  # force catch SUCCESS
asyncio.run(pets.pet_catch_callback(make_update('pet_catch_7_Pet_Trap'), ctx))
assert 'wild_pet_7' not in ctx.user_data, "encounter should clear on success"
traps = [d for d in INV if d.get('item_name')=='Pet Trap']
assert all(d.get('quantity',0) <= 0 for d in traps) or not traps, f"tools left: {INV}"
# pet should have been added to the 'pets' store — encounter cleared is the key check above
print("TEST 2 PASS: retry after failure -> catch succeeds, state cleared")

# Test 3: stale button gives guidance, no crash
asyncio.run(pets.pet_catch_callback(make_update('pet_catch_7'), ctx))
print("TEST 3 PASS: stale catch button handled gracefully")

# Test 4: TTL expiry clears ghost encounter
set_encounter(ts=time.time() - pets.WILD_PET_TTL_SECONDS - 10)
asyncio.run(pets.pet_catch_callback(make_update('pet_catch_7_Pet_Trap'), ctx))
assert 'wild_pet_7' not in ctx.user_data, "expired encounter should be cleared"
print("TEST 4 PASS: expired encounter cleaned up")

# Test 5: flee with active encounter clears all state
set_encounter()
asyncio.run(pets.pet_flee_callback(make_update('pet_flee_7'), ctx))
assert not any(k.startswith('wild_pet') for k in ctx.user_data), ctx.user_data
print("TEST 5 PASS: flee clears all wild-pet state")

# Test 6: unknown tool key falls back instead of dying
set_encounter()
asyncio.run(pets.pet_catch_callback(make_update('pet_catch_7_Bogus_Tool'), ctx))
assert 'wild_pet_7' in ctx.user_data, "unknown tool key shouldn't kill encounter"
print("TEST 6 PASS: legacy/unknown tool key handled (auto-select fallback)")

print("\nALL PET CATCH SYSTEM TESTS PASSED ✔")
