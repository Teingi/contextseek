# GIS Examples

地理空间场景示例，展示 ContextSeek 在位置感知应用中的能力。

## 运行前提（所有示例通用）

- OceanBase >= 4.2.2
- 环境变量：

```bash
export STORAGE_BACKEND=oceanbase
export OB_DSN="mysql+pymysql://root@127.0.0.1:2881/contextseek"
export GEO_ENABLED=true
```

也可以在各示例文件开头的配置区修改。

---

## poi_search.py — 地图 POI 搜索

```bash
uv run python examples/gis/poi_search.py
```

演示：
- 批量写入 POI（餐厅、加油站、地铁站等）
- 关键词 + 地理位置双路混合召回（phrase + geo）
- `geo_decay_score` 对远距离 POI 降权
- `GeoAwareMerger` 聚合附近 POI 到 knowledge 层

---

## ride_hailing.py — 打车调度场景

```bash
uv run python examples/gis/ride_hailing.py
```

演示：
- 写入司机位置（driver）、乘客订单（order）、热力区域（zone）
- 按乘客位置召回附近司机（半径搜索）
- 按多边形区域召回区域内活跃订单
- Stage 演进：位置更新 `extracted` → 聚合 `knowledge`

---

## autonomous_driving.py — 智能驾驶场景

```bash
uv run python examples/gis/autonomous_driving.py
```

演示：
- 写入高精地图要素：HD 道路、车道线、交叉路口
- 写入 ODD 区域（Operational Design Domain）
- 写入实时道路事件（施工、事故、限速）
- ODD 边界判断：车辆是否在可运营区域内
- 自动驾驶决策点附近的上下文召回
- 证据链：路况事件如何影响决策层知识

---

## ev_swap_planning.py — 电动车换电规划

```bash
uv run python examples/gis/ev_swap_planning.py
```

演示：
- 写入换电站（swap_station）和充电站（charge_station）
- 基于车辆当前位置 + 剩余电量推荐最近换电站
- 沿规划路线搜索途经换电站
- 换电站实时状态更新（电池库存）
- Stage 演进：实时 IoT 数据 `raw → extracted → knowledge` 层聚合
