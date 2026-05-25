"""GIS 电动车换电规划示例 — OceanBase 后端。

演示内容：
1. 写入换电站（swap_station）和充电站（charge_station）
2. 基于车辆当前位置 + 剩余电量推荐最近换电站
3. 沿规划路线搜索途经换电站
4. 换电站实时状态更新（电池库存）
5. Stage 演进：实时 IoT 数据 raw → extracted → knowledge 层聚合

运行前提：
- STORAGE_BACKEND=oceanbase（OB >= 4.2.2）
- GEO_ENABLED=true
"""

import os

os.environ.setdefault("STORAGE_BACKEND", "oceanbase")
os.environ.setdefault("OB_DSN", "mysql+pymysql://root@127.0.0.1:2881/contextseek")
os.environ.setdefault("GEO_ENABLED", "true")
os.environ.setdefault("GEO_DEFAULT_RADIUS_KM", "20.0")
os.environ.setdefault("GEO_DISTANCE_DECAY_KM", "2.0")
os.environ.setdefault("RETRIEVAL_RECALL_ROUTES", '["phrase","terms","geo"]')

import contextseek as cs
from contextseek.domain.geo import GeoPoint, GeoQuery

SCOPE = "ev/swap_demo"
client = cs.ContextSeek()

# =============================================================================
# 1. 写入换电站数据
# =============================================================================
print("=== 写入换电站 ===")

swap_stations = [
    {
        "station_id": "swap_001",
        "name": "蔚来换电站（朝阳路店）",
        "brand": "NIO",
        "battery_slots": 13,
        "available_batteries": 9,
        "avg_swap_minutes": 5,
        "open_24h": True,
        "lat": 39.9200,
        "lon": 116.4800,
    },
    {
        "station_id": "swap_002",
        "name": "蔚来换电站（国贸店）",
        "brand": "NIO",
        "battery_slots": 13,
        "available_batteries": 4,
        "avg_swap_minutes": 5,
        "open_24h": True,
        "lat": 39.9090,
        "lon": 116.4580,
    },
    {
        "station_id": "swap_003",
        "name": "奥动换电站（建外大街）",
        "brand": "AULTON",
        "battery_slots": 20,
        "available_batteries": 15,
        "avg_swap_minutes": 3,
        "open_24h": False,
        "lat": 39.9085,
        "lon": 116.4650,
    },
    {
        "station_id": "swap_004",
        "name": "蔚来换电站（望京店）",
        "brand": "NIO",
        "battery_slots": 13,
        "available_batteries": 11,
        "avg_swap_minutes": 5,
        "open_24h": True,
        "lat": 39.9950,
        "lon": 116.4800,
    },
    {
        "station_id": "swap_005",
        "name": "协鑫能科换电站（通州）",
        "brand": "JIHE",
        "battery_slots": 30,
        "available_batteries": 22,
        "avg_swap_minutes": 4,
        "open_24h": True,
        "lat": 39.9100,
        "lon": 116.6500,
    },
]

station_items = {}
for s in swap_stations:
    # 可用电量评分：库存充足 = 高重要性
    availability_ratio = s["available_batteries"] / s["battery_slots"]
    item = cs.ContextItem(
        content={
            "station_id": s["station_id"],
            "name": s["name"],
            "brand": s["brand"],
            "battery_slots": s["battery_slots"],
            "available_batteries": s["available_batteries"],
            "avg_swap_minutes": s["avg_swap_minutes"],
            "open_24h": s["open_24h"],
            "geo": {
                "lat": s["lat"],
                "lon": s["lon"],
                "geo_type": "swap_station",
            },
        },
        scope=SCOPE,
        tags=["swap_station", s["brand"].lower(), "open_24h" if s["open_24h"] else "limited_hours"],
        stage=cs.Stage.knowledge,
        stability=cs.Stability.stable,
        importance=0.5 + 0.5 * availability_ratio,
        provenance=cs.Provenance(
            source_type=cs.SourceType.iot_telemetry,
            confidence=0.95,
            context=f"Station telemetry {s['station_id']}",
        ),
    )
    client.store(item, scope=SCOPE)
    station_items[s["station_id"]] = item
    avail_icon = "✓" if s["available_batteries"] >= 3 else "⚠"
    print(f"  {avail_icon} {s['name']} 电池={s['available_batteries']}/{s['battery_slots']}")

# =============================================================================
# 2. 写入充电站（作为换电站的备选方案）
# =============================================================================
print("\n=== 写入充电站（备选方案）===")

charge_stations = [
    {
        "station_id": "charge_001",
        "name": "特斯拉超充站（朝阳大悦城）",
        "charger_count": 12,
        "available": 8,
        "max_kw": 250,
        "lat": 39.9320,
        "lon": 116.4820,
    },
    {
        "station_id": "charge_002",
        "name": "星星充电（建国路）",
        "charger_count": 20,
        "available": 15,
        "max_kw": 120,
        "lat": 39.9070,
        "lon": 116.4700,
    },
]

for c in charge_stations:
    item = cs.ContextItem(
        content={
            "station_id": c["station_id"],
            "name": c["name"],
            "charger_count": c["charger_count"],
            "available": c["available"],
            "max_kw": c["max_kw"],
            "geo": {"lat": c["lat"], "lon": c["lon"], "geo_type": "charge_station"},
        },
        scope=SCOPE,
        tags=["charge_station"],
        stage=cs.Stage.knowledge,
        stability=cs.Stability.stable,
        importance=c["available"] / c["charger_count"],
        provenance=cs.Provenance(source_type=cs.SourceType.api, confidence=0.9),
    )
    client.store(item, scope=SCOPE)
    print(f"  写入充电站: {c['name']} ({c['available']}/{c['charger_count']} 空闲)")

# =============================================================================
# 3. 车辆低电量告警 → 查找最近换电站
# =============================================================================
print("\n=== 低电量告警：查找最近换电站 ===")

# 车辆当前在国贸附近，电量 15%
vehicle_pos = GeoPoint(lat=39.9095, lon=116.4620)
remaining_soc = 15  # %
estimated_range_km = 40  # 剩余续航

print(f"  车辆位置: ({vehicle_pos.lat}, {vehicle_pos.lon})")
print(f"  剩余电量: {remaining_soc}%，估计续航: {estimated_range_km}km")

# 在续航范围内搜索换电站
search_radius = min(estimated_range_km * 0.8, 30.0)  # 80% 续航作为搜索半径，上限 30km
geo_q = GeoQuery(
    center=vehicle_pos,
    radius_km=search_radius,
    geo_types=["swap_station"],
)

hits = client.retrieve(
    query="换电站 电池 可用",
    scope=SCOPE,
    k=5,
    geo_query=geo_q,
)

print(f"\n  续航内（{search_radius}km）换电站（共 {len(hits)} 个）：")
for i, h in enumerate(hits):
    content = h.item.content if isinstance(h.item.content, dict) else {}
    available = content.get("available_batteries", "?")
    avg_time = content.get("avg_swap_minutes", "?")
    open_24h = content.get("open_24h", False)
    print(
        f"    {i+1}. [{h.score:.3f}] {content.get('name','?')} "
        f"| 电池库存={available} | 换电{avg_time}min | {'24h' if open_24h else '限时'}"
    )

if hits:
    best = hits[0]
    print(f"\n  ★ 推荐换电站: {best.item.content.get('name','?')}")

# =============================================================================
# 4. 沿规划路线搜索换电站（长途出行场景）
# =============================================================================
print("\n=== 长途规划：北京→天津途经换电站 ===")

# 北京→天津高速简化路线
beijing_tianjin_route = (
    "LINESTRING("
    "116.4500 39.9000, "   # 北京东出口
    "116.5500 39.7500, "   # 京津高速中段
    "116.7000 39.5000, "   # 廊坊附近
    "117.0000 39.2000, "   # 天津入口
    "117.2000 39.1000"     # 天津市区
    ")"
)

geo_route = GeoQuery(
    route_wkt=beijing_tianjin_route,
    route_radius_km=5.0,  # 高速路旁 5km 内
    geo_types=["swap_station", "charge_station"],
)

hits = client.retrieve(
    query="换电站 充电站",
    scope=SCOPE,
    k=10,
    geo_query=geo_route,
)

print(f"  路线沿途能量补给站（共 {len(hits)} 个）：")
for h in hits:
    content = h.item.content if isinstance(h.item.content, dict) else {}
    geo_type = content.get("geo", {}).get("geo_type", "?")
    icon = "⚡" if geo_type == "swap_station" else "🔌"
    print(f"    {icon} [{h.score:.3f}] [{geo_type}] {content.get('name','?')}")

# =============================================================================
# 5. 实时状态更新：换电站电池库存变化（IoT 遥测）
# =============================================================================
print("\n=== 实时状态更新：换电站 swap_002 电池补充 ===")

# 模拟 IoT 遥测更新：swap_002 完成了一次电池补充
updated_item = cs.ContextItem(
    content={
        "station_id": "swap_002",
        "name": "蔚来换电站（国贸店）",
        "brand": "NIO",
        "battery_slots": 13,
        "available_batteries": 10,  # 从 4 增加到 10
        "avg_swap_minutes": 5,
        "open_24h": True,
        "update_reason": "battery_replenishment",
        "geo": {
            "lat": 39.9090,
            "lon": 116.4580,
            "geo_type": "swap_station",
        },
    },
    scope=SCOPE,
    tags=["swap_station", "nio", "open_24h"],
    stage=cs.Stage.extracted,
    stability=cs.Stability.transient,
    importance=10 / 13,  # 新可用率
    provenance=cs.Provenance(
        source_type=cs.SourceType.iot_telemetry,
        confidence=0.98,
        context="Battery replenishment event",
    ),
)
client.store(updated_item, scope=SCOPE)
print("  ✓ swap_002 电池库存更新: 4 → 10")

# 重新查询验证更新
hits2 = client.retrieve(
    query="国贸换电站",
    scope=SCOPE,
    k=3,
    geo_query=GeoQuery(center=GeoPoint(lat=39.9090, lon=116.4580), radius_km=0.5),
)
print(f"  更新后查询结果（共 {len(hits2)} 条）：")
for h in hits2:
    c = h.item.content if isinstance(h.item.content, dict) else {}
    print(
        f"    [{h.score:.3f}] {c.get('name','?')} "
        f"电池库存={c.get('available_batteries','?')}"
    )

# =============================================================================
# 6. 换电效率统计（知识聚合）
# =============================================================================
print("\n=== 换电效率知识聚合 ===")

# 召回所有换电站，构建区域换电能力摘要
all_stations_geo = GeoQuery(
    center=GeoPoint(lat=39.9500, lon=116.5000),
    radius_km=50.0,
    geo_types=["swap_station"],
)
all_hits = client.retrieve(query="换电站", scope=SCOPE, k=20, geo_query=all_stations_geo)

total_slots = 0
total_available = 0
brands: dict = {}
for h in all_hits:
    c = h.item.content if isinstance(h.item.content, dict) else {}
    slots = c.get("battery_slots", 0)
    avail = c.get("available_batteries", 0)
    brand = c.get("brand", "unknown")
    total_slots += slots
    total_available += avail
    brands[brand] = brands.get(brand, 0) + 1

print(f"  覆盖换电站: {len(all_hits)} 个")
print(f"  总电池槽位: {total_slots}，当前可用: {total_available}")
if total_slots > 0:
    print(f"  整体可用率: {total_available/total_slots*100:.1f}%")
print(f"  品牌分布: {brands}")

# 将统计摘要存为 knowledge 层条目
if all_hits:
    summary_item = cs.ContextItem(
        content={
            "report_type": "swap_capacity_summary",
            "station_count": len(all_hits),
            "total_slots": total_slots,
            "total_available": total_available,
            "availability_pct": round(total_available / total_slots * 100, 1) if total_slots else 0,
            "brand_distribution": brands,
            "geo": {"lat": 39.9500, "lon": 116.5000, "geo_type": "poi"},
        },
        scope=SCOPE,
        tags=["knowledge", "swap_capacity", "summary"],
        stage=cs.Stage.knowledge,
        stability=cs.Stability.transient,
        importance=0.85,
        links=[cs.Link(target_id=h.item.id, relation=cs.LinkType.aggregated_from) for h in all_hits[:5]],
        provenance=cs.Provenance(
            source_type=cs.SourceType.inference,
            confidence=0.9,
            context="Aggregated from swap station telemetry",
        ),
    )
    client.store(summary_item, scope=SCOPE)
    print("  ✓ 换电能力摘要已写入 knowledge 层")

print("\n✓ 电动车换电规划示例完成")
