"""落霞宗静态数据。可改为 YAML/JSON 加载，结构保持不变。"""

from __future__ import annotations

BACKGROUND = """
落霞宗曾是东域数一数二的剑宗。掌门落云子十五年前以一剑「落霞惊鸿」震慑四方。
落云子已不在人世——对外称坐化，实则死于玄阴殿下毒；宗门无真正掌权宗主，表面秩序由执法长老沈监察与大师兄云烨共同维持。
近日一封署玄阴殿的密信称「落霞秘境」将开、有大机缘——此为假信。护山阵阵眼已种血阴咒，开启仪式即是引爆；林溯为玄阴殿内应（自认只是削弱护山、借势争位，不知会炸宗）。
宗门至宝「落霞剑髓」由落云子临终交洛晴藏匿。多数弟子仅知「秘境机缘」的公开说法。
玩家以客卿弟子身份借住修炼。劫数倒计时与自然日并行，无为则世界自转向危。
""".strip()

LOCATIONS = [
    {"id": "gate", "name": "山门", "summary": "落霞宗门户，盘查往来。", "tags": ["入口", "start_open", "public"]},
    {"id": "square", "name": "落霞广场", "summary": "宗门枢纽，人声与传谣汇聚。", "tags": ["公共", "start_open", "public", "social"]},
    {"id": "mission", "name": "任务堂", "summary": "差遣、情报与「机缘」筹备。", "tags": ["职司", "gated", "order"]},
    {"id": "law", "name": "执法堂", "summary": "刑狱、禁足、通告起草。", "tags": ["职司", "刑", "gated", "order", "archive"]},
    {"id": "hall", "name": "宗主殿", "summary": "空置权位与落云子牌位，仪式仍在。", "tags": ["权力真空", "gated", "order"]},
    {"id": "elder", "name": "长老院", "summary": "长老议事起居。", "tags": ["职司", "gated", "order"]},
    {"id": "library", "name": "藏经阁", "summary": "典籍禁书，旧事碎片。", "tags": ["秘", "gated", "archive", "secluded"]},
    {"id": "arena", "name": "演武场", "summary": "比试切磋之地。", "tags": ["武", "gated", "public"]},
    {"id": "kitchen", "name": "伙房膳堂", "summary": "烟火与八卦的锅炉。", "tags": ["生活", "start_open", "public", "social"]},
    {"id": "dorm_outer", "name": "外门客居", "summary": "外门与客卿落脚处。", "tags": ["生活", "start_open", "public"]},
    {"id": "dorm_inner", "name": "内门居所", "summary": "亲传与内门起居。", "tags": ["生活", "gated", "secluded"]},
    {"id": "backhill", "name": "后山", "summary": "静修、密会与阴影。", "tags": ["偏僻", "gated", "secluded"]},
]

# 单向声明，pack 内补双向
EDGES = {
    "gate": ["square", "dorm_outer"],
    "square": ["gate", "mission", "law", "kitchen", "arena", "library", "dorm_outer", "hall"],
    "mission": ["square"],
    "law": ["square", "elder"],
    "hall": ["square", "elder"],
    "elder": ["law", "hall"],
    "library": ["square", "backhill"],
    "arena": ["square", "dorm_inner"],
    "kitchen": ["square", "dorm_outer"],
    "dorm_outer": ["gate", "square", "kitchen"],
    "dorm_inner": ["arena", "backhill", "hall"],
    "backhill": ["library", "dorm_inner"],
}

ACTORS = [
    {
        "id": "player",
        "display_name": "客卿弟子",
        "title": "客卿",
        "summary": "借住修炼的外来者，名义上由客司照应。",
        "personality": "由玩家决定",
        "drives": "生存、查清真相或自己的目标",
        "is_player": True,
        "drive_priority": 0,
        "default_location": "dorm_outer",
        "extra": {"realm": "炼气"},
    },
    {
        "id": "da_shi_xiong",
        "display_name": "云烨",
        "title": "大师兄",
        "summary": "表面沉稳负责，实则独自扛压、暗中取证。",
        "personality": "外沉稳，内偏执紧绷，不轻信人",
        "drives": "查清宗门暗流，护住残局",
        "drive_priority": 100,
        "default_location": "square",
        "tags": ["investigator"],
        "extra": {"realm": "筑基后期"},
    },
    {
        "id": "er_shi_xiong",
        "display_name": "林溯",
        "title": "二师兄",
        "summary": "风流会说话，宗门人缘极广。",
        "personality": "洒脱、圆融、善于藏锋",
        "drives": "维持人设；借玄阴扶持争位；不知血阴会炸宗",
        "drive_priority": 95,
        "default_location": "square",
        "tags": ["social", "hidden_allegiance"],
        "extra": {"realm": "筑基中期"},
    },
    {
        "id": "san_shi_jie",
        "display_name": "苏婉",
        "title": "三师姐",
        "summary": "冷艳高傲，执着规矩与传统。",
        "personality": "冷傲、好正统、厌混乱",
        "drives": "按她认为正确的方式主持宗门秩序",
        "drive_priority": 90,
        "default_location": "square",
        "tags": ["order"],
        "extra": {"realm": "筑基中期"},
    },
    {
        "id": "shi_mei",
        "display_name": "洛晴",
        "title": "小师妹",
        "summary": "天赋极高却冷淡寡言，身负师父遗秘与落霞剑髓。",
        "personality": "冷淡、谨慎；想求助却极难信人",
        "drives": "守遗命、护落霞剑髓、查师父死因；可信之人出现前独自承受",
        "drive_priority": 92,
        "default_location": "backhill",
        "tags": ["reclusive"],
        "extra": {"realm": "炼气巅峰"},
    },
    {
        "id": "zhang_lao_fa",
        "display_name": "沈监察",
        "title": "执法长老",
        "summary": "程序正义，与云烨共同维持表面秩序。",
        "personality": "冷、疑、讲规矩",
        "drives": "肃纪、查案、必要时通告全宗",
        "drive_priority": 88,
        "can_proclaim": True,
        "default_location": "law",
        "tags": ["law", "investigator"],
        "extra": {"realm": "结丹中期"},
    },
    {
        "id": "ren_wu_tang_zhu",
        "display_name": "赵浦",
        "title": "任务堂堂主",
        "summary": "精明，经手差事与「秘境」相关筹备。",
        "personality": "精明、交换感强",
        "drives": "任务、人情与情报流通",
        "drive_priority": 70,
        "default_location": "square",
        "tags": ["social"],
        "extra": {"realm": "筑基中期"},
    },
    {
        "id": "cang_jing_guan",
        "display_name": "明镜",
        "title": "藏经阁管事",
        "summary": "守阁如命，旧录中或有血阴与剑髓来历。",
        "personality": "洁癖、守规则",
        "drives": "守典籍、审借阅",
        "drive_priority": 65,
        "default_location": "library",
        "tags": ["reclusive"],
        "extra": {"realm": "筑基初期"},
    },
    {
        "id": "zhi_fa_si",
        "display_name": "韩铁",
        "title": "执法堂司事",
        "summary": "执行长老令，做笔录抓人。",
        "personality": "刻板尽职",
        "drives": "执行命令",
        "drive_priority": 30,
        "default_location": "law",
        "tags": ["functional", "law"],
        "extra": {"realm": "筑基初期"},
    },
    {
        "id": "huo_fang_tou",
        "display_name": "刘大壮",
        "title": "伙房管事",
        "summary": "热心耳软，宗门八卦锅炉。",
        "personality": "热心、碎嘴、耳软",
        "drives": "开饭、听传话",
        "drive_priority": 25,
        "default_location": "kitchen",
        "tags": ["functional", "gossip"],
        "extra": {"realm": "炼气"},
    },
    {
        "id": "men_wei",
        "display_name": "岳山",
        "title": "山门护卫",
        "summary": "死板盘查，守门不讲情面。",
        "personality": "死板、脸黑",
        "drives": "守门",
        "drive_priority": 20,
        "default_location": "gate",
        "tags": ["functional"],
        "extra": {"realm": "筑基初期"},
    },
    {
        "id": "ke_qing_yin",
        "display_name": "白问舟",
        "title": "客司执事",
        "summary": "对接客卿日常，公事公办。",
        "personality": "客气、有分寸",
        "drives": "安顿客卿、传安排",
        "drive_priority": 35,
        "default_location": "dorm_outer",
        "tags": ["functional"],
        "extra": {"realm": "筑基初期"},
    },
]

STATE_SEEDS = {
    "player": {
        "location": "dorm_outer",
        "identity": {"sect_role": "guest_disciple", "title": "客卿弟子"},
        "cultivation": {"realm": "炼气", "layer": 3},
        "resources": {"spirit_stones": 30},
        "inventory": [{"item_id": "token_guest", "name": "客卿令", "qty": 1}],
    },
    "da_shi_xiong": {
        "location": "square",
        "identity": {"title": "大师兄"},
        "cultivation": {"realm": "筑基", "layer": 8},
        "resources": {"spirit_stones": 80},
    },
    "er_shi_xiong": {
        "location": "square",
        "identity": {"title": "二师兄"},
        "cultivation": {"realm": "筑基", "layer": 5},
        "resources": {"spirit_stones": 60},
        # 内应；不知血阴会炸宗；不知下毒杀师（玄阴未坦白）
        "flags": {
            "allegiance": "xuanyin",
            "believes_curse_only_weakens_array": True,
            "knows_master_poisoned": False,
        },
    },
    "san_shi_jie": {
        "location": "square",
        "identity": {"title": "三师姐"},
        "cultivation": {"realm": "筑基", "layer": 6},
        "resources": {"spirit_stones": 50},
    },
    "shi_mei": {
        "location": "square",
        "identity": {"title": "小师妹"},
        "cultivation": {"realm": "炼气", "layer": 9, "talent": "high"},
        "resources": {"spirit_stones": 20},
        "flags": {
            "knows_treasure_lost": True,
            "holds_luoxia_jian_sui": True,
            "knows_master_poisoned": True,
            "wants_help_but_distrusts": True,
        },
    },
    "zhang_lao_fa": {
        "location": "law",
        "identity": {"title": "执法长老", "can_proclaim": True},
        "cultivation": {"realm": "结丹", "layer": 2},
        "resources": {"spirit_stones": 200},
    },
    "ren_wu_tang_zhu": {
        "location": "square",
        "identity": {"title": "任务堂堂主"},
        "cultivation": {"realm": "筑基", "layer": 4},
        "resources": {"spirit_stones": 70},
    },
    "cang_jing_guan": {
        "location": "library",
        "identity": {"title": "藏经阁管事"},
        "cultivation": {"realm": "筑基", "layer": 2},
        "resources": {"spirit_stones": 40},
    },
    "zhi_fa_si": {
        "location": "law",
        "identity": {"title": "执法堂司事"},
        "cultivation": {"realm": "筑基", "layer": 1},
        "resources": {"spirit_stones": 25},
    },
    "huo_fang_tou": {
        "location": "kitchen",
        "identity": {"title": "伙房管事"},
        "cultivation": {"realm": "炼气", "layer": 2},
        "resources": {"spirit_stones": 15},
    },
    "men_wei": {
        "location": "gate",
        "identity": {"title": "山门护卫"},
        "cultivation": {"realm": "筑基", "layer": 1},
        "resources": {"spirit_stones": 20},
    },
    "ke_qing_yin": {
        "location": "dorm_outer",
        "identity": {"title": "客司执事"},
        "cultivation": {"realm": "筑基", "layer": 1},
        "resources": {"spirit_stones": 30},
    },
}

BELIEF_SEEDS = [
    {
        "belief_id": "b_public_secret_realm",
        "holder_id": "ren_wu_tang_zhu",
        "proposition": "近日落霞秘境将开，是宗门大机缘",
        "source": "told_by",
        "source_detail": "宗内传阅的玄阴殿来信说法",
        "truth_rel": "conflicts_authority",
        "confidence": 0.7,
        "day": 1,
    },
    {
        "belief_id": "b_public_secret_realm_lin",
        "holder_id": "er_shi_xiong",
        "proposition": "秘境开启将按计划推进（对我方有利）",
        "source": "self",
        "truth_rel": "matches_authority",
        "confidence": 0.9,
        "day": 1,
    },
]

WORLD_FLAGS = {
    "no_living_master": True,
    "fake_secret_realm_letter": True,
    "blood_curse_planted": True,
    "blood_curse_host_unknown": True,
    "xuanyin_countdown": 21,
    "secret_realm_is_trigger": True,
    "master_luoyun_poisoned_by_xuanyin": True,  # 权威隐秘；对玩家置灰直至信念坐实
    "treasure_is_luoxia_jian_sui": True,
    "jian_sui_required_for_disarm": False,  # 拍板：破阵不强制剑髓
    "map_unlocked": [],
    "seal_mountain": False,
}

# 日终额外权重（内容配置）；键为 countdown 上限档
EVOLVE_WEIGHT_BY_COUNTDOWN = {
    21: {},
    14: {
        "da_shi_xiong": 10,
        "er_shi_xiong": 15,
        "zhang_lao_fa": 5,
    },
    10: {
        "da_shi_xiong": 25,
        "er_shi_xiong": 35,
        "san_shi_jie": 15,
        "shi_mei": 20,
        "zhang_lao_fa": 15,
        "ren_wu_tang_zhu": 10,
    },
    5: {
        "da_shi_xiong": 40,
        "er_shi_xiong": 50,
        "san_shi_jie": 30,
        "shi_mei": 35,
        "zhang_lao_fa": 25,
        "cang_jing_guan": 10,
    },
}
