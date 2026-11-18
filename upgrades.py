"""Большой набор улучшений и производные характеристики игрока."""
import random

UPGRADES = [
    {"id":"max_hp","name":"Живучесть +1","desc":"Максимум здоровья +1 и мгновенное лечение","color":(95,235,155)},
    {"id":"dmg","name":"Калибр +9%","desc":"Каждый выстрел наносит больше урона","color":(255,76,94)},
    {"id":"fire_rate","name":"Перегрев ствола","desc":"Стреляй заметно быстрее","color":(255,211,92)},
    {"id":"move","name":"Турбодвигатель","desc":"Скорость движения и разгона выше","color":(65,220,255)},
    {"id":"dash","name":"Фазовый привод","desc":"Рывок быстрее перезаряжается","color":(112,202,196)},
    {"id":"pierce","name":"Рельсотрон","desc":"Снаряды пробивают больше врагов","color":(165,120,255)},
    {"id":"lifesteal","name":"Кровавый контракт","desc":"Убийства иногда восстанавливают здоровье","color":(245,75,205)},
    {"id":"magnet","name":"Гравитационный магнит","desc":"Подбирай предметы с большого расстояния","color":(255,145,76)},
    {"id":"pulse_gain","name":"БЫСТРЫЙ ЗАРЯД ЩИТА","desc":"Убийства быстрее заряжают щит","color":(194,135,171)},
    {"id":"crit","name":"Критический контур","desc":"Шанс критического урона +10%","color":(255,170,80)},
    {"id":"multishot","name":"БОКОВОЙ ЗАЛП","desc":"Два дополнительных снаряда по сторонам","color":(65,220,255)},
    {"id":"bullet_speed","name":"Гиперскорость","desc":"Снаряды летят быстрее и дальше","color":(100,185,255)},
    {"id":"bullet_size","name":"Тяжёлые боеприпасы","desc":"Пули крупнее и наносят больше урона","color":(255,190,90)},
    {"id":"regen","name":"Нанорегенерация","desc":"Восстанавливай здоровье со временем","color":(95,235,155)},
    {"id":"armor","name":"Бронепластина","desc":"Каждый 4-5-й полученный удар игнорируется","color":(140,195,255)},
    {"id":"pulse_power","name":"УСИЛЕННЫЙ ЩИТ","desc":"Щит выдерживает на одно попадание больше","color":(210,120,255)},
    {"id":"dash_damage","name":"Таран","desc":"Рывок наносит огромный урон врагам","color":(255,100,80)},
]
MAX_STACKS = {
    "max_hp":10,"dmg":4,"fire_rate":3,"move":3,"dash":2,"pierce":2,
    "lifesteal":1,"magnet":2,"pulse_gain":3,"crit":3,"multishot":1,
    "bullet_speed":2,"bullet_size":2,"regen":2,"armor":2,"pulse_power":2,
    "dash_damage":2,
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
    p.max_hp=5+min(10,u.get("max_hp",0))
    p.dmg=1.0+0.09*min(4,u.get("dmg",0))
    p.fire_rate=0.16/(1.0+0.10*min(3,u.get("fire_rate",0)))
    p.move_spd=2800.0*(1.0+0.05*min(3,u.get("move",0)))
    p.dash_cd_max=1.05*(0.90**min(2,u.get("dash",0)))
    p.pierce=min(2,u.get("pierce",0))
    p.lifesteal=min(1,u.get("lifesteal",0))
    p.magnet=1.0+0.22*min(2,u.get("magnet",0))
    p.pulse_gain=1.0+0.16*min(3,u.get("pulse_gain",0))
    p.crit=min(0.30,0.10*min(3,u.get("crit",0)))
    p.multishot=min(1,u.get("multishot",0))
    p.bullet_speed=1.0+0.12*min(2,u.get("bullet_speed",0))
    p.bullet_size=1.0+0.16*min(2,u.get("bullet_size",0))
    p.regen=0.0+0.025*min(2,u.get("regen",0))
    p.armor=min(2,u.get("armor",0))
    p.pulse_power=1.0+0.25*min(2,u.get("pulse_power",0))
    p.dash_damage=1.0+0.35*min(2,u.get("dash_damage",0))
