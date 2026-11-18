"""Большой набор улучшений и производные характеристики игрока."""
import random

UPGRADES = [
    {"id":"max_hp","name":"Живучесть +1","desc":"Максимум здоровья +1 и мгновенное лечение","color":(143,190,151)},
    {"id":"dmg","name":"Калибр +12%","desc":"Каждый выстрел наносит больше урона","color":(208,112,112)},
    {"id":"fire_rate","name":"Перегрев ствола","desc":"Стреляй заметно быстрее","color":(224,190,120)},
    {"id":"move","name":"Турбодвигатель","desc":"Скорость движения и разгона выше","color":(112,202,196)},
    {"id":"dash","name":"Фазовый привод","desc":"Рывок быстрее перезаряжается","color":(112,202,196)},
    {"id":"pierce","name":"Рельсотрон","desc":"Снаряды пробивают больше врагов","color":(157,145,198)},
    {"id":"lifesteal","name":"Кровавый контракт","desc":"Убийства иногда восстанавливают здоровье","color":(194,135,171)},
    {"id":"magnet","name":"Гравитационный магнит","desc":"Подбирай предметы с большого расстояния","color":(214,151,103)},
    {"id":"pulse_gain","name":"Накопитель","desc":"Заряд импульса растёт быстрее","color":(194,135,171)},
    {"id":"crit","name":"Критический контур","desc":"Шанс критического урона +10%","color":(255,170,100)},
    {"id":"multishot","name":"Раздвоение","desc":"Дополнительный снаряд в каждом залпе","color":(100,210,245)},
    {"id":"bullet_speed","name":"Гиперскорость","desc":"Снаряды летят быстрее и дальше","color":(120,190,255)},
    {"id":"bullet_size","name":"Тяжёлые боеприпасы","desc":"Пули крупнее и наносят больше урона","color":(235,190,120)},
    {"id":"regen","name":"Нанорегенерация","desc":"Восстанавливай здоровье со временем","color":(130,230,160)},
    {"id":"armor","name":"Бронепластина","desc":"Каждый четвёртый полученный удар игнорируется","color":(150,180,220)},
    {"id":"pulse_power","name":"Сингулярность","desc":"Импульс бьёт сильнее и отбрасывает дальше","color":(210,130,235)},
    {"id":"dash_damage","name":"Таран","desc":"Рывок наносит огромный урон врагам","color":(255,130,110)},
    {"id":"xp_gain","name":"Охотничий контракт","desc":"Получай на 20% больше очков за каждое убийство","color":(235,220,120)},
    {"id":"combo","name":"Азарт охоты","desc":"Комбо держится дольше и множитель выше","color":(255,150,190)},
]
MAX_STACKS = {
    "max_hp":3,"dmg":5,"fire_rate":4,"move":4,"dash":3,"pierce":3,
    "lifesteal":2,"magnet":3,"pulse_gain":4,"crit":4,"multishot":3,
    "bullet_speed":3,"bullet_size":3,"regen":3,"armor":3,"pulse_power":4,
    "dash_damage":3,"xp_gain":4,"combo":3,
}
UPGRADES_BY_ID = {u["id"]:u for u in UPGRADES}

def available_upgrades(player=None):
    if player is None:
        return list(UPGRADES)
    return [u for u in UPGRADES if player.upgrades.get(u["id"],0) < MAX_STACKS[u["id"]]]

def roll_upgrades(rng,n=3,player=None):
    pool=available_upgrades(player)
    return [u["id"] for u in rng.sample(pool,min(n,len(pool)))]

def apply_upgrade(player,upgrade_id):
    if upgrade_id not in UPGRADES_BY_ID or player.upgrades.get(upgrade_id,0)>=MAX_STACKS[upgrade_id]:
        return False
    player.upgrades[upgrade_id]=player.upgrades.get(upgrade_id,0)+1
    recompute(player)
    if upgrade_id=="max_hp":
        player.hp=min(player.max_hp,player.hp+1)
    return True

def recompute(p):
    u=p.upgrades
    p.max_hp=5+min(3,u.get("max_hp",0))
    p.dmg=1.0+0.12*min(5,u.get("dmg",0))
    p.fire_rate=0.14/(1.0+0.13*min(4,u.get("fire_rate",0)))
    p.move_spd=3000.0*(1.0+0.07*min(4,u.get("move",0)))
    p.dash_cd_max=0.9*(0.86**min(3,u.get("dash",0)))
    p.pierce=min(3,u.get("pierce",0))
    p.lifesteal=min(2,u.get("lifesteal",0))
    p.magnet=1.0+0.28*min(3,u.get("magnet",0))
    p.pulse_gain=1.0+0.22*min(4,u.get("pulse_gain",0))
    p.crit=min(0.45,0.10*min(4,u.get("crit",0)))
    p.multishot=min(3,u.get("multishot",0))
    p.bullet_speed=1.0+0.18*min(3,u.get("bullet_speed",0))
    p.bullet_size=1.0+0.22*min(3,u.get("bullet_size",0))
    p.regen=0.0+0.035*min(3,u.get("regen",0))
    p.armor=min(3,u.get("armor",0))
    p.pulse_power=1.0+0.35*min(4,u.get("pulse_power",0))
    p.dash_damage=1.0+0.65*min(3,u.get("dash_damage",0))
    p.xp_gain=1.0+0.20*min(4,u.get("xp_gain",0))
    p.score_gain=1.0+0.20*min(4,u.get("xp_gain",0))
    p.combo_bonus=min(3,u.get("combo",0))
