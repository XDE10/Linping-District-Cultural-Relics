# app.py
# requirements: streamlit, pandas, openpyxl (if .xlsx), xlrd (if .xls), pyproj
# pip install streamlit pandas openpyxl xlrd pyproj

import streamlit as st
import pandas as pd
import json
import re
import math
from pyproj import Transformer

# ==============================================================================
# Coordinate Transformation: CGCS2000 -> WGS84 -> GCJ-02
# ==============================================================================
# CGCS2000 (EPSG:4490) -> WGS84 (EPSG:4326) transformer
transformer = Transformer.from_crs("EPSG:4490", "EPSG:4326", always_xy=True)

# WGS84 to GCJ-02 Coordinate Conversion (Python Implementation)
PI = 3.1415926535897932384626
A = 6378245.0  # 地球长半轴
EE = 0.00669342162296594323  # 偏心率平方

def _transform_lat(lng, lat):
    """Helper function for latitude transformation."""
    ret = -100.0 + 2.0 * lng + 3.0 * lat + 0.2 * lat * lat + 0.1 * lng * lat + 0.2 * math.sqrt(abs(lng))
    ret += (20.0 * math.sin(6.0 * lng * PI) + 20.0 * math.sin(2.0 * lng * PI)) * 2.0 / 3.0
    ret += (20.0 * math.sin(lat * PI) + 40.0 * math.sin(lat / 3.0 * PI)) * 2.0 / 3.0
    ret += (160.0 * math.sin(lat / 12.0 * PI) + 320 * math.sin(lat / 30.0 * PI)) * 2.0 / 3.0
    return ret

def _transform_lng(lng, lat):
    """Helper function for longitude transformation."""
    ret = 300.0 + lng + 2.0 * lat + 0.1 * lng * lng + 0.1 * lng * lat + 0.1 * math.sqrt(abs(lng))
    ret += (20.0 * math.sin(6.0 * lng * PI) + 20.0 * math.sin(2.0 * lng * PI)) * 2.0 / 3.0
    ret += (20.0 * math.sin(lng * PI) + 40.0 * math.sin(lng / 3.0 * PI)) * 2.0 / 3.0
    ret += (150.0 * math.sin(lng / 12.0 * PI) + 300.0 * math.sin(lng / 30.0 * PI)) * 2.0 / 3.0
    return ret

def _out_of_china(lng, lat):
    """Checks if coordinates are outside of China."""
    return not (73.66 < lng < 135.05 and 3.86 < lat < 53.55)

def wgs84_to_gcj02(lng, lat):
    """
    Converts WGS84 coordinates to GCJ-02 coordinates.
    :param lng: WGS84 longitude
    :param lat: WGS84 latitude
    :return: A tuple (gcj_lng, gcj_lat)
    """
    if _out_of_china(lng, lat):
        return lng, lat
    
    d_lat = _transform_lat(lng - 105.0, lat - 35.0)
    d_lng = _transform_lng(lng - 105.0, lat - 35.0)
    
    rad_lat = lat / 180.0 * PI
    magic = math.sin(rad_lat)
    magic = 1 - EE * magic * magic
    sqrt_magic = math.sqrt(magic)
    
    d_lat = (d_lat * 180.0) / ((A * (1 - EE)) / (magic * sqrt_magic) * PI)
    d_lng = (d_lng * 180.0) / (A / sqrt_magic * math.cos(rad_lat) * PI)
    
    mg_lat = lat + d_lat
    mg_lng = lng + d_lng
    
    return mg_lng, mg_lat

def cgcs2000_to_gcj02(cgcs_lng, cgcs_lat):
    """
    Converts CGCS2000 coordinates to GCJ-02 coordinates.
    :param cgcs_lng: CGCS2000 longitude
    :param cgcs_lat: CGCS2000 latitude
    :return: A tuple (gcj_lng, gcj_lat)
    """
    wgs84_lng, wgs84_lat = transformer.transform(cgcs_lng, cgcs_lat)
    return wgs84_to_gcj02(wgs84_lng, wgs84_lat)

# ==============================================================================
# End of Coordinate Conversion Implementation
# ==============================================================================

CATEGORY_COLORS = {
    "古遗址": {"color": "#FF6B6B"},
    "石窟寺及石刻": {"color": "#4ECDC4"},
    "古建筑": {"color": "#45B7D1"},
    "近现代重要史迹及代表性建筑": {"color": "#FFA500"},
    "其他": {"color": "#95A5A6"}
}

st.set_page_config(layout="wide", page_title="文物点位地图展示")

st.markdown("""
<style>
[data-testid="stFileUploaderDropzone"] div div::before { content: "将文件拖放到此处"; }
[data-testid="stFileUploaderDropzone"] div div span { display: none; }
[data-testid="stFileUploaderDropzone"] div div::after {
    color: rgba(49, 51, 63, 0.6); font-size: .8em;
    content: "支持 .xlsx, .xls, .csv 格式";
}
[data-testid="stFileUploaderDropzone"] div div small { display: none; }
[data-testid="stFileUploaderDropzone"] button[data-testid="baseButton-secondary"] {
    visibility: hidden;
    position: relative;
}
[data-testid="stFileUploaderDropzone"] button[data-testid="baseButton-secondary"]::after {
    content: "浏览文件";
    visibility: visible;
    position: absolute;
    left: 0;
    right: 0;
    top: 0;
    bottom: 0;
    display: flex;
    align-items: center;
    justify-content: center;
}
</style>
""", unsafe_allow_html=True)

st.title("临平区不可移动文物分布")

# 从 secrets 读取高德地图 API key
try:
    amap_key = st.secrets["amap"]["api_key"]
except Exception as e:
    st.error("未能读取高德地图 API Key。请在 .streamlit/secrets.toml 中配置：\n```\n[amap]\napi_key = \"your_api_key_here\"\n```")
    amap_key = None

st.sidebar.header("上传与设置")
uploaded = st.sidebar.file_uploader("上传 Excel (.xlsx/.xls) 或 CSV 文件", type=["xlsx","xls","csv"])

dms_re = re.compile(r"(-?\d+)[^\d]+(\d+)[^\d]+(\d+(?:\.\d+)?)")
dms_re2 = re.compile(r"(-?\d+)[^\d]+(\d+(?:\.\d+)?)")

def parse_coord_py(v):
    if v is None: return None
    s = str(v).strip()
    if s == "": return None
    if re.fullmatch(r"-?\d+(\.\d+)?", s): return float(s)
    m = dms_re.search(s)
    if m:
        d, mm, ss = (float(g) for g in m.groups())
        sign = -1 if d < 0 else 1
        return sign * (abs(d) + mm/60.0 + ss/3600.0)
    m2 = dms_re2.search(s)
    if m2:
        d, mm = (float(g) for g in m2.groups())
        sign = -1 if d < 0 else 1
        return sign * (abs(d) + mm/60.0)
    return None

def detect_columns(headers):
    hmap = { str(h).strip().lower(): idx for idx, h in enumerate(headers) }
    def find(keys):
        for k in keys:
            if k in hmap: return hmap[k]
        for k in keys:
            for h_key, h_idx in hmap.items():
                if k in h_key: return h_idx
        return -1
    return {
        "name": find(["名称"]), "lat": find(["纬度"]), "lng": find(["经度"]),
        "addr": find(["地址"]), "era_specific": find(["具体时代"]),
        "era_broad": find(["时代"]), "category": find(["类别"]),
        "desc": find(["详细描述"]), "type": find(["类型"])
    }

def get_category_info(category_str):
    if not category_str: return CATEGORY_COLORS["其他"]
    for key in CATEGORY_COLORS.keys():
        if key != "其他" and key in category_str:
            return CATEGORY_COLORS[key]
    return CATEGORY_COLORS["其他"]

def sheet_to_points(df: pd.DataFrame):
    pts, category_stats = [], {}
    if df.empty: return pts, category_stats
    
    headers = list(df.columns)
    cols = detect_columns(headers)

    if cols["name"] == -1 or cols["lat"] == -1 or cols["lng"] == -1:
        st.error("解析失败：未能找到 **名称**、**纬度**、**经度** 的全部列。")
        st.write("检测到的表头为:", headers)
        return [], {}

    for _, row in df.iterrows():
        def get_val(key):
            idx = cols.get(key, -1)
            return str(row.iloc[idx]).strip() if idx != -1 and pd.notna(row.iloc[idx]) else ""

        name, lat_str, lng_str = get_val("name"), get_val("lat"), get_val("lng")
        lat, lng = parse_coord_py(lat_str), parse_coord_py(lng_str)
        
        if lat is not None and lng is not None:
            gcj_lng, gcj_lat = cgcs2000_to_gcj02(lng, lat)
            cat = get_val("category")
            
            category_key = "其他"
            for key in CATEGORY_COLORS.keys():
                if key != "其他" and cat and key in cat:
                    category_key = key
                    break
            category_stats[category_key] = category_stats.get(category_key, 0) + 1
            
            pts.append({
                "name": name, "lat": float(gcj_lat), "lng": float(gcj_lng),
                "addr": get_val("addr"), "era": get_val("era_specific") or get_val("era_broad"),
                "category": cat, "main_category": cat, "desc": get_val("desc"),
                "type": get_val("type"), "color": get_category_info(cat)["color"]
            })
    return pts, category_stats

HEADER_ROW_INDEX = 1

if 'points' not in st.session_state:
    st.session_state.points = []
if 'category_stats' not in st.session_state:
    st.session_state.category_stats = {}
if 'last_uploaded_filename' not in st.session_state:
    st.session_state.last_uploaded_filename = None

if uploaded:
    if uploaded.name != st.session_state.last_uploaded_filename:
        try:
            df = pd.read_csv(uploaded, header=HEADER_ROW_INDEX) if uploaded.name.lower().endswith(".csv") else pd.read_excel(uploaded, header=HEADER_ROW_INDEX)
            points, category_stats = sheet_to_points(df)
            st.session_state.points = points
            st.session_state.category_stats = category_stats
            st.session_state.last_uploaded_filename = uploaded.name
            
        except Exception as e:
            st.error(f"读取或解析文件失败：{e}")
            st.session_state.points, st.session_state.category_stats, st.session_state.last_uploaded_filename = [], {}, None
else:
    if st.session_state.last_uploaded_filename is not None:
        st.session_state.points, st.session_state.category_stats, st.session_state.last_uploaded_filename = [], {}, None

points = st.session_state.points
category_stats = st.session_state.category_stats

if category_stats:
    st.sidebar.markdown("---")
    st.sidebar.subheader("点位统计")
    for cat, count in sorted(category_stats.items()):
        color = CATEGORY_COLORS.get(cat, CATEGORY_COLORS["其他"])["color"]
        st.sidebar.markdown(f'<span style="color: {color};">●</span> {cat}: {count} 个', unsafe_allow_html=True)

if not points and not uploaded:
    st.info("请在左侧边栏上传 Excel/CSV 文件查看文物点位分布。")

# ---- display parsed data table ----
if points:
    st.markdown("#### 数据预览")
    df_to_show = pd.DataFrame(points)
    
    display_cols = ["name", "main_category", "era", "addr", "type", "lng", "lat"]
    display_df = df_to_show[[col for col in display_cols if col in df_to_show.columns]].copy()
    
    column_rename_map = {
        "name": "名称", "main_category": "类别", "era": "时代", "addr": "地址",
        "type": "类型", "lng": "经度", "lat": "纬度"
    }
    display_df.rename(columns=column_rename_map, inplace=True)
    
    display_df.index = range(1, len(display_df) + 1)
    display_df.rename_axis("序号", axis="index", inplace=True)
    
    st.dataframe(display_df)
    st.write("---")

# ---- render map ----
if points and amap_key:
    st.markdown(f"#### 地图展示")
    points_json = json.dumps(points, ensure_ascii=False)
    categories_json = json.dumps(CATEGORY_COLORS, ensure_ascii=False)
    
    html_content = f'''
<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>文物点位地图</title>
  <style>
    html, body, #map {{ height: 100%; margin: 0; padding: 0; font-family: Arial, sans-serif; }}
    .custom-marker {{
        width: 20px; height: 20px; border-radius: 50%;
        border: 2px solid #FFFFFF; box-shadow: 0 2px 5px rgba(0,0,0,0.4);
        cursor: pointer;
    }}
    .legend {{
      position: absolute; top: 10px; right: 10px;
      background: rgba(255, 255, 255, 0.95); padding: 12px;
      border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.2);
      z-index: 1000; font-size: 13px; max-width: 200px;
    }}
    .legend-title {{
      font-weight: bold; margin-bottom: 8px; padding-bottom: 4px; border-bottom: 1px solid #ddd;
    }}
    .legend-item {{
      display: flex; align-items: center; margin: 6px 0;
      cursor: pointer; transition: opacity 0.2s;
    }}
    .legend-item:hover {{ opacity: 0.8; }}
    .legend-marker {{
      width: 20px; height: 20px; border-radius: 50%;
      margin-right: 8px; border: 2px solid white;
      box-shadow: 0 1px 3px rgba(0,0,0,0.3);
    }}
    .map-controls {{
      position: absolute; top: 10px; left: 10px;
      background: rgba(255, 255, 255, 0.95); padding: 12px;
      border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.2);
      z-index: 1000; font-size: 13px;
    }}
    .map-controls .control-title {{
        font-weight: bold; margin-bottom: 8px; padding-bottom: 4px; border-bottom: 1px solid #ddd;
    }}
    .map-controls label {{
        display: flex; align-items: center; margin: 6px 0; cursor: pointer;
    }}
    .map-controls input {{ margin-right: 8px; }}
    .amap-info-window, .amap-info-content {{
      background: white !important; border: 1px solid #ccc !important;
      border-radius: 6px !important; box-shadow: 0 2px 8px rgba(0,0,0,0.2) !important;
    }}
    .amap-info-content {{ padding: 12px !important; min-width: 200px !important; }}
    .popup-content {{ max-width: 320px; font-size: 14px; line-height: 1.5; color: #333; }}
    .popup-title {{ 
      font-weight: bold; font-size: 16px; color: #2c3e50; 
      margin-bottom: 8px; border-bottom: 2px solid #3498db; padding-bottom: 4px; 
    }}
    .popup-type {{ 
      display: inline-block; background: #3498db; color: white; padding: 2px 8px; 
      border-radius: 12px; font-size: 12px; margin-bottom: 6px; 
    }}
    .popup-era {{ font-style: italic; color: #e67e22; font-size: 13px; margin-bottom: 4px; }}
    .popup-category {{ color: #27ae60; font-size: 13px; margin-bottom: 6px; font-weight: 500; }}
    .popup-address {{ 
      margin-top: 8px; font-size: 12px; color: #666; background: #f8f9fa; 
      padding: 6px; border-radius: 4px; border-left: 3px solid #3498db; 
    }}
    .popup-desc {{ 
      margin-top: 8px; font-size: 12px; color: #555; max-height: 100px; overflow-y: auto; 
      background: #f8f9fa; padding: 8px; border-radius: 4px; border-left: 3px solid #e74c3c; 
    }}
    .popup-coords {{ 
      margin-top: 8px; font-size: 11px; color: #888; text-align: center; 
      padding-top: 6px; border-top: 1px solid #eee; 
    }}
  </style>
  <script src="https://webapi.amap.com/maps?v=2.0&key={amap_key}"></script>
</head>
<body>
  <div id="map"></div>
  <div class="legend" id="legend"><div class="legend-title">图例</div></div>
  <div class="map-controls">
      <div class="control-title">地图显示设置</div>
      <label><input type="checkbox" id="poi-checkbox"> 显示POI标注</label>
      <label><input type="checkbox" id="road-checkbox"> 显示路网图层</label>
  </div>
  <script>
    try {{
      const points = {points_json};
      const categories = {categories_json};
      
      const map = new AMap.Map('map', {{
        zoom: 12, center: [120.25, 30.43], viewMode: '2D', resizeEnable: true,
        features: []
      }});
      
      map.add(new AMap.TileLayer.Satellite());
      
      const poiLayer = new AMap.TileLayer({{
          getTileUrl: (x, y, z) => `https://wprd01.is.autonavi.com/appmaptile?x=${{x}}&y=${{y}}&z=${{z}}&lang=zh_cn&size=1&scl=1&style=8&ltype=4`,
          zIndex: 130
      }});
      const roadNetLayer = new AMap.TileLayer.RoadNet({{ zIndex: 110 }});

      document.getElementById('poi-checkbox').addEventListener('change', function() {{
          this.checked ? map.add(poiLayer) : map.remove(poiLayer);
      }});
      document.getElementById('road-checkbox').addEventListener('change', function() {{
          this.checked ? map.add(roadNetLayer) : map.remove(roadNetLayer);
      }});

      const legendEl = document.getElementById('legend');
      const categoryCount = {{}};
      points.forEach(p => {{
        let catKey = '其他';
        for (let cat in categories) {{
          if (cat !== '其他' && p.main_category && p.main_category.includes(cat)) {{
            catKey = cat; break;
          }}
        }}
        categoryCount[catKey] = (categoryCount[catKey] || 0) + 1;
      }});
      
      for (let category in categories) {{
        if (categoryCount[category]) {{
          const item = document.createElement('div');
          item.className = 'legend-item';
          item.innerHTML = `<div class="legend-marker" style="background-color: ${{categories[category].color}}"></div><div>${{category}} (${{categoryCount[category]}})</div>`;
          legendEl.appendChild(item);
        }}
      }}
      
      map.on('complete', function() {{
        if (!points || points.length === 0) return;
        
        const escapeHtml = (s) => String(s || '').replace(/[&<>"']/g, (m) => ({{'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'": '&#39;'}}[m]));
        const markersByCategory = {{}};
        
        points.forEach(p => {{
          if (!p.lat || !p.lng) return;
          let catKey = '其他';
          for (let cat in categories) {{
            if (cat !== '其他' && p.main_category && p.main_category.includes(cat)) {{
              catKey = cat; break;
            }}
          }}
          if (!markersByCategory[catKey]) markersByCategory[catKey] = [];
          
          const marker = new AMap.Marker({{
            position: [p.lng, p.lat], title: p.name,
            content: `<div class="custom-marker" style="background-color: ${{p.color}}"></div>`,
            offset: new AMap.Pixel(-12, -12), extData: {{ category: catKey }}
          }});
          
          const infoHtml = `<div class="popup-content">
                              <div class="popup-title">${{escapeHtml(p.name)}}</div>
                              ${{p.type ? `<div class="popup-type">${{escapeHtml(p.type)}}</div>` : ''}}
                              ${{p.era ? `<div class="popup-era">时代：${{escapeHtml(p.era)}}</div>` : ''}}
                              ${{p.category ? `<div class="popup-category">类别：${{escapeHtml(p.category)}}</div>` : ''}}
                              ${{p.addr ? `<div class="popup-address">地址：${{escapeHtml(p.addr)}}</div>` : ''}}
                              ${{p.desc ? `<div class="popup-desc">详情：${{escapeHtml(p.desc)}}</div>` : ''}}
                              <div class="popup-coords">坐标：${{parseFloat(p.lng).toFixed(6)}}, ${{parseFloat(p.lat).toFixed(6)}}</div>
                            </div>`;
          
          const infoWindow = new AMap.InfoWindow({{ 
              content: infoHtml, 
              offset: new AMap.Pixel(0, -30),
              closeWhenClickMap: true, 
              size: new AMap.Size(300, 0), 
              autoMove: true
          }});

          infoWindow.on('open', function() {{
              setTimeout(() => {{
                  const allInfoContents = document.querySelectorAll('.amap-info-content');
                  allInfoContents.forEach(contentDom => {{
                      if (contentDom.offsetParent !== null) {{
                          contentDom.onwheel = function(e) {{
                              e.stopPropagation();
                          }};
                      }}
                  }});
              }}, 100);
          }});
          
          marker.on('click', () => infoWindow.open(map, marker.getPosition()));
          markersByCategory[catKey].push(marker);
        }});

        const allMarkers = [];
        document.querySelectorAll('.legend-item').forEach(item => {{
            const category = item.innerText.split(' ')[0];
            item.dataset.category = category;
            item.dataset.visible = 'true';
            map.add(markersByCategory[category]);
            allMarkers.push(...markersByCategory[category]);

            item.addEventListener('click', function() {{
                const cat = this.dataset.category;
                const isVisible = this.dataset.visible === 'true';
                if (isVisible) {{
                    map.remove(markersByCategory[cat]);
                    this.style.opacity = '0.4'; this.dataset.visible = 'false';
                }} else {{
                    map.add(markersByCategory[cat]);
                    this.style.opacity = '1'; this.dataset.visible = 'true';
                }}
            }});
        }});
        
        if (allMarkers.length > 0) map.setFitView(allMarkers, false, [60, 60, 60, 60], 15);
      }});
    }} catch(error) {{ console.error('初始化地图时发生错误:', error); }}
  </script>
</body>
</html>'''
    st.components.v1.html(html_content, height=700, scrolling=False)

elif uploaded and not points:
    pass

elif not uploaded and not amap_key:
    st.error("高德Key未设置。")