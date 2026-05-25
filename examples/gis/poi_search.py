"""GIS 地图 POI 搜索示例 — OceanBase 后端。

演示内容：
1. 批量写入 POI（餐厅、加油站、地铁站等）
2. 按关键词 + 地理位置做混合搜索（phrase + geo 双路召回）
3. 利用 geo_decay_score 对远距离 POI 降权
4. 聚合附近 POI 到 knowledge 层（GeoAwareMerger）

运行前提：
- STORAGE_BACKEND=oceanbase（OB >= 4.2.2）
- GEO_ENABLED=true
"""

import os

os.environ.setdefault("STORAGE_BACKEND", "oceanbase")
os.environ.setdefault("OB_DSN", "mysql+pymysql://root@127.0.0.1:2881/contextseek")
os.environ.setdefault("GEO_ENABLED", "true")
os.environ.setdefault("GEO_DEFAULT_RADIUS_KM", "3.0")
os.environ.setdefault("GEO_DISTANCE_DECAY_KM", "0.5")
os.environ.setdefault("RETRIEVAL_RECALL_ROUTES", '["phrase","terms","geo"]')

import contextseek as cs
from contextseek.domain.geo import GeoPoint, GeoQuery
from contextseek.policies.decay import geo_decay_score

SCOPE = "map/poi_demo"

client = cs.ContextSeek()

# =============================================================================
# 1. 写入 POI 数据
# =============================================================================
print("=== 写入 POI 数据 ===")

pois = [
    # 餐厅
    {"name": "海底捞火锅（西单店）", "category": "restaurant", "lat": 39.9122, "lon": 116.3726, "rating": 4.8},
    {"name": "全聚德烤鸭（前门店）", "category": "restaurant", "lat": 39.8982, "lon": 116.3975, "rating": 4.7},
    {"name": "庆丰包子铺（西长安街店）", "category": "restaurant", "lat": 39.9053, "lon": 116.3720, "rating": 4.3},
    # 加油站
    {"name": "中石化加油站（长安街西）", "category": "gas_station", "lat": 39.9085, "lon": 116.3680, "rating": 4.0},
    {"name": "中石油加油站（复兴门）", "category": "gas_station", "lat": 39.9107, "lon": 116.3588, "rating": 4.1},
    # 地铁站
    {"name": "西单地铁站（1号线/4号线）", "category": "metro", "lat": 39.9114, "lon": 116.3728, "rating": 4.5},
    {"name": "复兴门地铁站（1号线/2号线）", "category": "metro", "lat": 39.9105, "lon": 116.3589, "rating": 4.4},
    # 购物中心
    {"name": "西单大悦城", "category": "mall", "lat": 39.9130, "lon": 116.3725, "rating": 4.6},
    {"name": "君太百货", "category": "mall", "lat": 39.9120, "lon": 116.3732, "rating": 4.2},
]

for p in pois:
    item = cs.ContextItem(
        content={
            "name": p["name"],
            "category": p["category"],
            "rating": p["rating"],
            "geo": {"lat": p["lat"], "lon": p["lon"], "geo_type": "poi"},
        },
        scope=SCOPE,
        tags=["poi", p["category"]],
        stage=cs.Stage.knowledge,
        stability=cs.Stability.stable,
        importance=min(1.0, p["rating"] / 5.0),
        provenance=cs.Provenance(source_type=cs.SourceType.hd_map_provider, confidence=0.92),
    )
    client.store(item, scope=SCOPE)
    print(f"  写入 POI: {p['name']} ({p['category']}) @ ({p['lat']}, {p['lon']})")

# =============================================================================
# 2. 混合搜索：用户在西单附近搜索"烤鸭"
# =============================================================================
print("\n=== 混合搜索：烤鸭（西单附近） ===")

user_pos = GeoPoint(lat=39.9110, lon=116.3720)
geo_q = GeoQuery(center=user_pos, radius_km=5.0, geo_types=["poi"])

hits = client.retrieve(
    query="烤鸭 餐厅",
    scope=SCOPE,
    k=5,
    geo_query=geo_q,
)

print(f"  搜索结果（共 {len(hits)} 条）：")
for h in hits:
    content = h.item.content if isinstance(h.item.content, dict) else {}
    geo = content.get("geo", {})
    # 手动计算地理衰减展示
    geo_factor = geo_decay_score(
        {"lat": geo.get("lat"), "lon": geo.get("lon")},
        user_pos,
        decay_km=0.5,
    )
    print(
        f"    [{h.score:.3f}] {content.get('name','?')} "
        f"评分={content.get('rating','?')} "
        f"地理衰减={geo_factor:.3f}"
    )

# =============================================================================
# 3. 按类别过滤的地理搜索：附近加油站
# =============================================================================
print("\n=== 附近加油站搜索 ===")

geo_q2 = GeoQuery(center=user_pos, radius_km=3.0, geo_types=["poi"])

hits = client.retrieve(
    query="加油站",
    scope=SCOPE,
    k=5,
    tags=["gas_station"],
    geo_query=geo_q2,
)

print(f"  附近加油站（共 {len(hits)} 个）：")
for h in hits:
    content = h.item.content if isinstance(h.item.content, dict) else {}
    print(
        f"    [{h.score:.3f}] {content.get('name','?')} "
        f"@ ({content.get('geo', {}).get('lat','?')}, {content.get('geo', {}).get('lon','?')})"
    )

# =============================================================================
# 4. 无地理约束的语义搜索对比
# =============================================================================
print("\n=== 对比：无地理约束的搜索（火锅） ===")

hits_no_geo = client.retrieve(
    query="火锅 餐厅",
    scope=SCOPE,
    k=5,
)

print(f"  语义搜索结果（共 {len(hits_no_geo)} 条）：")
for h in hits_no_geo:
    content = h.item.content if isinstance(h.item.content, dict) else {}
    print(f"    [{h.score:.3f}] {content.get('name','?')} 类别={content.get('category','?')}")

# =============================================================================
# 5. POI 聚合演示（GeoAwareMerger）
# =============================================================================
print("\n=== POI 聚合：将西单周边相似 POI 合并为知识节点 ===")

from contextseek.evolution.merger import GeoAwareMerger

# 查询西单附近的 POI 作为待聚合候选
geo_q3 = GeoQuery(center=GeoPoint(lat=39.9120, lon=116.3728), radius_km=0.3, geo_types=["poi"])
candidates_hits = client.retrieve(query="购物 地铁 餐厅", scope=SCOPE, k=20, geo_query=geo_q3)
candidate_items = [h.item for h in candidates_hits]

if len(candidate_items) >= 2:
    merger = GeoAwareMerger(
        similarity_threshold=0.5,
        min_cluster_size=2,
        spatial_merge_threshold_m=200.0,  # 200m 内的同类 POI 触发合并
    )
    kept, archived = merger.merge(candidate_items)
    print(f"  候选 {len(candidate_items)} 条 → 合并后保留 {len(kept)} 条，归档 {len(archived)} 条")
    knowledge_items = [it for it in kept if it.stage == cs.Stage.knowledge]
    print(f"  新增 knowledge 节点 {len(knowledge_items) - len([it for it in candidate_items if it.stage == cs.Stage.knowledge])} 个")
else:
    print(f"  候选条数不足（{len(candidate_items)}），跳过聚合演示")

print("\n✓ 地图 POI 搜索示例完成")
