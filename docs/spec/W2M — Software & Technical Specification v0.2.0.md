# W2M — Software & Technical Specification v0.2.0

**Phiên bản:** 0.2.0 — Draft for Review · 
**Trạng thái:** Proposed · 
**Loại dự án:** Web Application / Graph Optimization / Geospatial Computing


## 1. Tổng quan dự án

### 1.1. Giới thiệu

W2M (Where to meet) là ứng dụng web giúp 4 người tìm vị trí gặp nhau hợp lý dựa trên mạng lưới giao thông thực tế. Hệ thống không dùng trung điểm tọa độ hay khoảng cách đường chim bay, mà dùng đường đi ngắn nhất trên đồ thị giao thông có hướng.

Trong MVP, hệ thống nhận tọa độ của 4 người và trả về tối đa 5 vị trí gặp phù hợp nhất. Các vị trí là node của mạng đường, không phụ thuộc dữ liệu nhà hàng, quán cà phê hay địa điểm kinh doanh.

### 1.2. Mục tiêu chính

1. Tìm vị trí gặp cân bằng giữa hai đòi hỏi: không ai phải đi quá xa (công bằng) và cả nhóm không tốn quá nhiều thời gian (hiệu quả).
2. **Không bao giờ xếp một điểm lên trên một điểm khác tốt hơn hoặc bằng nó với cả 4 người** (tính Pareto-tối ưu).
3. Tính theo đường đi thực tế, tôn trọng hướng đường một chiều.
4. Hiển thị điểm gặp cùng tuyến đường ngắn nhất từ mỗi thành viên.
5. Cho phép người dùng điều chỉnh mức ưu tiên giữa công bằng và hiệu quả.
6. Làm nền tảng để mở rộng sang giao thông thời gian thực và nhiều phương tiện.

### 1.3. Định nghĩa thành công

MVP được xem là hoàn thành khi:

- Người dùng chọn được 4 vị trí bất kỳ trong phạm vi hỗ trợ.
- Backend snap được 4 tọa độ lên mạng đường và tính được offset tiếp cận của từng người.
- Hệ thống tính được thời gian ngắn nhất từ cả 4 nguồn đến các node có thể tiếp cận.
- Hệ thống xếp hạng theo hàm mục tiêu ở mục 3.4 và trả về tối đa 5 điểm gặp, trong đó điểm hạng 1 Pareto-tối ưu và thứ hạng nhất quán với quan hệ trội.
- Frontend hiển thị các điểm gặp cùng 4 tuyến đường tương ứng.
- Thông số thời gian, khoảng cách và điểm số khớp với backend theo quy tắc làm tròn ở mục 3.6.

## 2. Phạm vi triển khai

### 2.1. Phạm vi địa lý

**Khu vực:** Nội thành Hà Nội, đề xuất là khu đô thị bên trong Vành đai 3 sau khi xác định ranh giới chính xác. Ranh giới là một polygon GeoJSON `AOI`, cấu hình được mà không đổi thuật toán.

Hai vùng được phân biệt rõ:

| Vùng | Định nghĩa | Dùng cho |
| --- | --- | --- |
| `AOI` | Polygon hỗ trợ | Kiểm tra đầu vào; tập ứng viên điểm gặp |
| `ROUTING_AREA` | `AOI` mở rộng một vùng đệm `BUFFER_M` | Xây đồ thị và chạy Dijkstra |

`BUFFER_M` mặc định **3 000 m**, là giá trị cần kiểm nghiệm. Vùng đệm quá hẹp làm mất các đường vòng ra ngoài AOI, khiến thời gian của người ở sát biên bị ước lượng quá cao. Tiêu chí chấp nhận: với 200 cặp điểm ngẫu nhiên trong dải 1 km sát biên, thời gian ngắn nhất tính với `BUFFER_M` và với `2 × BUFFER_M` lệch nhau không quá 1% ở ít nhất 99% số cặp (TC-15).

Yêu cầu:

- 4 vị trí đầu vào phải nằm trong `AOI`.
- Điểm gặp trả về phải nằm trong `AOI`.
- Tuyến đường được phép đi qua `ROUTING_AREA`.

### 2.2. Giới hạn MVP

| Thuộc tính | Quy định |
| --- | --- |
| Số người | Chính xác 4 (thuật toán viết tổng quát cho K người) |
| Phương tiện | Ô tô trong bản tính toán đầu tiên |
| Địa điểm gặp | Node gốc của đồ thị, nằm trong `AOI` |
| Thuật toán | Single-source Dijkstra chạy K lần, có cutoff |
| Hàm mục tiêu | OWA đơn điệu với tham số công bằng $φ$ (mục 3.4) |
| Trọng số cạnh | Thời gian di chuyển ước lượng, không đổi theo giờ |
| Nguồn bản đồ | OpenStreetMap |
| Giao thông thời gian thực | Chưa hỗ trợ |
| Số điểm gợi ý | Tối đa 5 |
| Tài khoản người dùng | Không yêu cầu |

**Lý do tạm chọn ô tô:** OSMnx có cấu hình `drive` để dựng đồ thị đường bộ. Xe máy cần bộ quy tắc đường riêng và được phát triển sau. Đây là giả định kỹ thuật cần review (D-02).

### 2.3. Ngoài phạm vi MVP

- Tìm kiếm nhà hàng, quán ăn, quán cà phê.
- Giao thông thời gian thực và trọng số theo giờ.
- Theo dõi vị trí trực tiếp của người dùng.
- Dự đoán pha đèn tín hiệu.
- Nhiều loại phương tiện trong cùng một nhóm.
- Điều hướng GPS từng chặng.
- Điểm gặp nằm giữa cạnh (sai số của việc bỏ qua được chặn ở mục 3.7).
- Thời gian quay về từ điểm gặp (chỉ tối ưu chiều đi).
- Đăng nhập, tạo nhóm, lưu lịch sử.
- Tối ưu theo sở thích hoặc trọng số riêng của từng người.

## 3. Mô hình toán học

Hệ thống chọn node có điểm OWA nhỏ nhất trên vector thời gian của 4 người. Vì mọi trọng số đều dương, điểm được chọn luôn Pareto-tối ưu. Một tham số $φ ∈ [0, 1]$ điều chỉnh từ hiệu quả (trung bình) sang công bằng (gần minimax).

### 3.1. Biểu diễn bản đồ

Mạng giao thông là đồ thị có hướng, có trọng số, cho phép nhiều cạnh song song (MultiDiGraph):


$$G = (V, E, \tau), \qquad \tau : E \to \mathbb{R}_{>0}$$


- $V$: tập node, mỗi node có ID, vĩ độ, kinh độ (WGS84) và tọa độ phẳng $(x, y)$ theo EPSG:32648.
- $E$: tập cạnh có hướng. Đường hai chiều có hai cạnh ngược nhau; đường một chiều chỉ có một.
- $τ(e)$: thời gian đi hết cạnh, đơn vị giây, luôn dương.

Với cạnh song song giữa cùng cặp $(u, w)$, Dijkstra dùng cạnh có $τ$ nhỏ nhất. Khi dựng lại tuyến phải lấy đúng cạnh đó (key nhỏ nhất nếu hòa).

Đồ thị sản xuất chỉ giữ **thành phần liên thông mạnh lớn nhất** của đồ thị dựng trên `ROUTING_AREA`. Nhờ đó mọi node đều tới được mọi node khác, và lỗi “không có node chung” chỉ còn do cutoff thời gian.

### 3.2. Mô hình trọng số


$$\tau(e) = \frac{\ell(e)}{v(e)}$$


- $ℓ(e)$: chiều dài hình học của cạnh, đo trên EPSG:32648, đơn vị mét.
- $v(e)$: tốc độ di chuyển ước lượng, m/s, lấy từ bảng cấu hình theo loại đường, có phiên bản `weight_profile_version`.
- `maxspeed` chỉ là cận trên: $v(e) = min(v_{bảng}(\text{loại đường}), maxspeed)$. Không dùng `maxspeed` làm tốc độ thực tế.
- Trọng số không đổi theo thời điểm truy vấn.

#### 3.2.1. Bảng tốc độ (speed profile)

$v_{bảng}(\text{loại đường})$ là tốc độ di chuyển trung bình giả định, tra theo tag `highway` của OSM trong file `config/speed_profiles/car-v1.yaml`. Đây là tốc độ đi thực tế ước lượng (đã tính mật độ giao thông thông thường), không phải giới hạn tốc độ theo luật.


$$v(e) = \min\big(v_{\text{bảng}}(\text{highway}(e)),\; \text{maxspeed}(e)\big)$$


Cạnh không có `maxspeed` hợp lệ thì $v(e) = v_{bảng}$. `maxspeed` là cận trên: đường biển 40 km/h không bao giờ được tính nhanh hơn 40, nhưng cũng không bị giả định là đi đúng 40.

Giá trị khởi điểm cho `car-v1`, **chỉ để minh họa, chưa hiệu chỉnh**:

| `highway` (OSM) | $v_{bảng}$ (km/h) | $v_{bảng}$ (m/s) |
| --- | --- | --- |
| motorway | 60 | 16.7 |
| trunk | 40 | 11.1 |
| primary | 30 | 8.3 |
| secondary | 25 | 6.9 |
| tertiary | 22 | 6.1 |
| $\text{motorway}_{link}$, $\text{trunk}_{link}$, $\text{primary}_{link}$, $\text{secondary}_{link}$, $\text{tertiary}_{link}$ | 25 | 6.9 |
| residential, $\text{living}_{street}$ | 18 | 5.0 |
| service, unclassified | 12 | 3.3 |
| `default` (mọi giá trị khác) | 15 | 4.2 |

Cấu trúc file:

```yaml
weight_profile_version: car-v1
travel_mode: car
unit: kmh
speeds:
  motorway: 60
  trunk: 40
  primary: 30
  secondary: 25
  tertiary: 22
  motorway_link: 25
  trunk_link: 25
  primary_link: 25
  secondary_link: 25
  tertiary_link: 25
  residential: 18
  living_street: 18
  service: 12
  unclassified: 12
  default: 15
maxspeed_cap: true
```

**Quy tắc tra:**

1. `highway` dạng danh sách (OSMnx gộp nhiều đoạn): lấy loại có $v_{bảng}$ thấp nhất.
2. Loại không có trong bảng: dùng `default` và ghi số cạnh rơi vào `default` trong báo cáo `validate_graph.py`.
3. `maxspeed` được phân tích thành $km/h$: số thuần là $km/h$; có hậu tố `mph` thì nhân 1.609; giá trị danh sách lấy nhỏ nhất; giá trị chữ (`signals`, `none`, `walk`…) hoặc ≤ 0 thì bỏ qua.
4. Đổi sang $m/s$ (chia 3.6) trước khi lấy min và tính $τ(e)$.
5. Kiểm tra $v(e) > 0$ với mọi cạnh.

**Hiệu chỉnh:** lấy mẫu tối thiểu 100 tuyến trong AOI, so thời gian mô hình với một dịch vụ ETA độc lập ngoài giờ cao điểm, rồi chỉnh từng dòng theo loại đường chiếm phần lớn chiều dài tuyến. Mỗi lần đổi bảng thì tăng `weight_profile_version` và dựng lại đồ thị. Bảng tĩnh không phản ánh giờ cao điểm; đây là giới hạn đã nêu ở mục 2.3.

### 3.3. Thời gian của từng người

Người $i ∈ {1, …, K}$ (MVP: $K = 4$, nhãn $A–D$) có tọa độ gốc $pᵢ$. Snapping (FR-03) cho ra nguồn tạm $sᵢ$ trên cạnh $eᵢ$ và khoảng cách vuông góc $rᵢ$ từ $pᵢ$ tới đường. Thời gian của người $i$ tới node $v$ là:


$$T_i(v) = a_i + \delta_i(v), \qquad a_i = \frac{r_i}{v_{\text{access}}}$$


- $δᵢ(v)$: thời gian ngắn nhất từ $sᵢ$ tới $v$ trên đồ thị của request, tính bằng Dijkstra theo chiều cạnh.
- $aᵢ$: offset tiếp cận, là thời gian đi từ vị trí gốc ra đường. Mặc định $v_{access} = 1.4 m/s$ (đi bộ), cần review.
- Vì $rᵢ ≤$ `SNAP_MAX_M` $= 150 m$ nên $aᵢ ≤ 107 s$.

Cạnh $e = (u, w)$ có $τ(e)$, điểm chiếu nằm ở tỉ lệ $θ ∈ [0, 1]$ theo chiều dài tính từ $u$. Nguồn tạm $sᵢ$ có các cạnh ra sau:

$$
s_i \to w : (1 - \theta)\,\tau(u, w) \qquad\qquad s_i \to u : \theta\,\tau(w, u) \;\text{ (chỉ khi cạnh } (w, u) \text{ tồn tại)}
$$

Nguồn chỉ cần cạnh ra, không cần cạnh vào. Đồ thị dùng chung không bị sửa (FR-03).

### 3.4. Hàm mục tiêu

Với mỗi node v, sắp vector thời gian theo thứ tự giảm dần: 
$$ T₍₁₎(v) ≥ T₍₂₎(v) ≥ … ≥ T_{(K)}(v)$$. 
Điểm số là trung bình có trọng số theo thứ tự (OWA):

$$
\operatorname{Score}_\varphi(v) = \sum_{k=1}^{K} w_k(\varphi)\, T_{(k)}(v), \qquad w_k(\varphi) = \frac{\beta^{\,k-1}}{\sum_{j=1}^{K} \beta^{\,j-1}}, \qquad \beta = 1 - 0.9\,\varphi
$$

$φ ∈ [0, 1]$ là mức ưu tiên công bằng, mặc định $φ = 0.5$. Trọng số với $K = 4$:

| $φ$ | $w₁$ (người xa nhất) | $w₂$ | $w₃$ | $w₄$ (người gần nhất) | Ý nghĩa |
| --- | --- | --- | --- | --- | --- |
| 0 | 0.2500 | 0.2500 | 0.2500 | 0.2500 | Trung bình: tối ưu tổng thời gian cả nhóm |
| 0.5 | 0.4953 | 0.2724 | 0.1498 | 0.0824 | Mặc định: cân bằng |
| 1 | 0.9001 | 0.0900 | 0.0090 | 0.0009 | Gần minimax: tối ưu người đến muộn nhất |

**Tính chất** (đều được kiểm thử ở mục 12):

1. **Đơn điệu chặt, nên Pareto-tối ưu.** Nếu $Tᵢ(u) ≤ Tᵢ(v)$ với mọi $i$ và bất đẳng thức chặt ở ít nhất một $i$, thì $Score(u) < Score(v)$. Lý do: sắp xếp bảo toàn thứ tự từng thành phần, tổng nhỏ hơn chặt, và mọi $w_k > 0$.
2. **Thưởng công bằng.** Vì $w₁ ≥ w₂ ≥ … ≥ w_K$, hàm là Schur-lồi: với cùng tổng thời gian, phân bố đều hơn không bao giờ bị điểm tệ hơn.
3. **Cùng đơn vị giây và bị kẹp:** $T_{avg}(v) ≤ Score(v) ≤ T_{max}(v)$. Score đọc được như “thời gian đại diện của nhóm”.
4. **Tịnh tiến:** cộng cùng một hằng số $c$ vào mọi $Tᵢ$ thì Score tăng đúng $c$ (vì tổng trọng số bằng 1).
5. **Cận dưới theo người xa nhất:** $Score(v) ≥ w₁ · T_{max}(v)$, dùng cho dừng sớm ở mục 5.4.

**Vì sao bỏ công thức cũ.** Công thức v0.1.0 là $T_{max} + λ(T_{max} − T_{min}) = (1 + λ)T_{max} − λT_{min}$, tức OWA với trọng số $(1 + λ, 0, 0, −λ)$. Trọng số âm làm hàm thưởng cho việc người gần nhất phải đi xa hơn. Ví dụ (phút):

| Điểm | A | B | C | D | Score v0.1.0 ($λ = 1$) | Score v0.2.0 ($φ = 0.5$) | Score v0.2.0 ($φ = 1$) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| P | 10 | 10 | 10 | 30 | 50 | **19.91** | **28.00** |
| Q | 26 | 27 | 28 | 31 | **36** (được chọn) | 29.17 | 30.69 |

$Q$ tệ hơn $P$ với cả 4 người nhưng công thức cũ lại chọn $Q$. Công thức mới chọn $P$ với mọi $φ$.

Các đại lượng $T_{max}$, $T_{min}$, $Delta = T_{max} − T_{min}$ và $T_{avg}$ vẫn được tính và hiển thị để người dùng tham khảo, nhưng không tham gia xếp hạng.

### 3.5. Điều kiện hợp lệ

Node $v$ là ứng viên khi và chỉ khi:

1. $v$ là node gốc của $G$ (không phải nguồn tạm) và nằm trong `AOI`.
2. $δᵢ(v)$ hữu hạn với mọi $i$.
3. $Tᵢ(v) ≤$ `T_LIMIT` với mọi $i$. Mặc định `T_LIMIT` $= 3600 s$.
4. $v$ không bị loại bởi quy tắc loại trừ có dữ liệu hỗ trợ (ví dụ node trên đường cao tốc hoặc cầu vượt, nếu có bảng loại trừ).

Do điều kiện 3, Dijkstra từ $sᵢ$ dùng cutoff riêng `T_LIMIT − aᵢ`. Cutoff này loại đúng và đủ các node vi phạm điều kiện 3.

Nếu không có ứng viên, hệ thống trả về `NO_COMMON_REACHABLE_NODE` kèm gợi ý `T_LIMIT` tối thiểu cần thiết nếu đã biết (xem FR-09).

**Lưu ý:** Hàm mục tiêu không bảo đảm thời gian của 4 người bằng nhau, cũng không bảo đảm điểm gặp là nơi dừng hoặc đỗ xe an toàn.

### 3.6. Số học và làm tròn

- Backend tính bằng số thực 64-bit, đơn vị giây.
- Trước khi so sánh, $Tᵢ(v)$ và $Score(v)$ được lượng tử về bước $0.1 s$ : $q(x) = round(10x) / 10$. Score được tính từ thời gian đã lượng tử, rồi lượng tử lần nữa.
- Thứ tự xếp hạng: $q(Score)$ tăng dần $→ q(T_{max})$ tăng dần $→ q(T_{avg})$ tăng dần → node ID tăng dần. Thứ tự này là toàn phần và tất định.
- API trả giá trị đã lượng tử. Frontend không tự tính lại Score, chỉ làm tròn khi hiển thị: phút làm tròn đến 1 chữ số thập phân, từng giá trị làm tròn độc lập từ số giây.
- Sai số cho phép giữa tổng trọng số tuyến và $δᵢ(v)$: $|Στ − δᵢ(v)| ≤ 10⁻⁶ · δᵢ(v) + 10⁻³ s$.

### 3.7. Giới hạn của mô hình và cận sai số

**Chỉ xét node.** Gọi $p$ là một điểm bất kỳ trên cạnh $e = (u, w)$. Mọi người tới $p$ từ phía $u$ có thể đi tiếp tới $w$, còn người tới từ phía $w$ đã qua $w$ trước đó. Do đó $Tᵢ(w) ≤ Tᵢ(p) + τ(e)$ với mọi $i$. Theo tính đơn điệu và tịnh tiến:

$$
\min_{v \in V} \operatorname{Score}(v) \;\le\; \operatorname{Score}(p^{*}) + \max_{e \in E_{\text{AOI}}} \tau(e)
$$

với $p*$ là điểm tối ưu liên tục trên cạnh. Bước kiểm tra đồ thị phải báo cáo P50, P99 và max của $τ(e)$ trong AOI. Cạnh có $τ(e) >$ `MAX_EDGE_SECONDS` (mặc định 60 s) được chia nhỏ khi tiền xử lý để chặn sai số này.

**Các giả định khác:**

- Không tính chi phí rẽ, chờ đèn hay cấm rẽ. Thời gian bị đánh giá thấp có hệ thống, nhiều hơn với tuyến đi qua nhiều nút giao. Sai lệch này khác nhau giữa 4 người nên ảnh hưởng trực tiếp tới đánh giá công bằng. Lời giải về sau là Dijkstra theo cạnh (mục 10.2).
- Chỉ tối ưu chiều đi. Trên đồ thị có hướng, thời gian về có thể khác thời gian đi.
- Tốc độ là giá trị cấu hình, không phải đo đạc. Kết quả là thời gian ước lượng, không phải ETA.

## 4. Yêu cầu chức năng

### FR-01: Hiển thị bản đồ

Frontend hiển thị bản đồ Hà Nội với: kéo, thu phóng; ranh giới `AOI`; đặt và kéo marker; phân biệt marker người dùng với marker điểm gặp; tuyến đường dạng polyline; ghi công OpenStreetMap.

### FR-02: Nhập vị trí 4 người

Người dùng chọn 4 điểm xuất phát trên bản đồ. Mỗi điểm gồm `id`, `lat`, `lon` (WGS84).

- Tọa độ phải hợp lệ $(lat ∈ [−90, 90], lon ∈ [−180, 180], \text{số hữu hạn})$ và nằm trong `AOI`.
- Các điểm được phép trùng nhau.
- Có thể chỉnh sửa trước khi tính; không bắt buộc GPS thực.

### FR-03: Ánh xạ tọa độ vào đồ thị (snapping)

1. Chiếu tọa độ gốc sang EPSG:32648.
2. Dùng STRtree tìm các cạnh trong bán kính `SNAP_MAX_M` $= 150 m$. Chỉ xét cạnh thuộc đồ thị sản xuất (đã lọc theo SCC lớn nhất).
3. Chọn cạnh có khoảng cách vuông góc $rᵢ$ nhỏ nhất. Hòa thì chọn cạnh có ID nhỏ nhất. Với đường hai chiều, hai cạnh ngược nhau trùng hình học được xử lý như một đoạn.
4. Tính tỉ lệ $θ$ của điểm chiếu theo chiều dài từ $u$.
5. Tạo nguồn tạm $sᵢ$ với các cạnh ra theo mục 3.3. Nếu $θ = 0$ hoặc $θ = 1$ thì dùng thẳng node $u$ hoặc $w$.
6. Ghi lại $rᵢ$ và offset $aᵢ = rᵢ / v_{access}$.

Nguồn tạm chỉ tồn tại trong phạm vi request, dưới dạng lớp phủ (overlay) trên đồ thị dùng chung. Không sửa đồ thị dùng chung. Không có cạnh trong ngưỡng thì trả `SNAP_FAILED`.

UI hiển thị đoạn nối từ vị trí gốc tới điểm snap khi $rᵢ > 30 m$, và hiển thị $aᵢ$ như một phần của thời gian của người đó.

### FR-04: Tính thời gian ngắn nhất

Chạy Dijkstra riêng cho từng nguồn $sᵢ$ trên đồ thị của request, trọng số $τ$, cutoff `T_LIMIT − aᵢ`. Mỗi lần chạy trả về:

- `dist_i`: node → $δᵢ(node)$, chỉ gồm node trong cutoff.
- `pred_i`: node → (node trước, key cạnh), dùng để dựng tuyến ở FR-07.

Không cần biết điểm gặp trước khi chạy.

### FR-05: Đánh giá ứng viên

Với mỗi node v thỏa mục 3.5: tính $Tᵢ(v) = aᵢ + δᵢ(v)$, rồi $Score_φ(v)$, $T_{max}$, $T_{min}$, $Delta$, $T_{avg}$, đã lượng tử theo mục 3.6. Node không có trong một `dist_i` bất kỳ bị loại.

### FR-06: Xếp hạng và đa dạng không gian

1. Sắp ứng viên theo thứ tự toàn phần ở mục 3.6.
2. Duyệt tham lam theo thứ tự đó: nhận ứng viên nếu khoảng cách Euclid (EPSG:32648) tới mọi điểm đã nhận ≥ `MIN_SPACING_M` $= 500 m$.
3. Dừng khi đủ `TOP_K` = 5 hoặc hết ứng viên.

Không nới `MIN_SPACING_M` khi thiếu ứng viên; trả về ít hơn 5 điểm. Chỉ có hạng 1 được bảo đảm Pareto-tối ưu; các hạng sau là phương án thay thế ở vị trí khác.

### FR-07: Dựng tuyến đường

Với mỗi điểm gặp được chọn, dựng 4 tuyến từ `pred_i` của chính lần Dijkstra đã dùng để xếp hạng. Polyline ghép từ hình học thực của từng cạnh (kể cả nửa cạnh từ nguồn tạm), không nối tọa độ node bằng đoạn thẳng. Tổng τ của tuyến phải bằng $δᵢ(v)$ trong sai số ở mục 3.6.

### FR-08: Hiển thị kết quả

```text
Meeting Point #1                 (21.0285, 105.8542)

A: 12.0 phút   (gồm 0.8 phút ra đường)
B: 14.0 phút
C: 13.0 phút
D: 11.0 phút

Xa nhất: 14.0 phút · Chênh lệch: 3.0 phút · Trung bình: 12.5 phút
Điểm nhóm (φ = 0.5): 13.2 phút
```

Số liệu là ví dụ; “Điểm nhóm” đúng với các thời gian trên và $φ = 0.5$. Nhãn ghi rõ đây là thời gian ước lượng. Chọn một kết quả để xem 4 tuyến.

### FR-09: Điều chỉnh mức công bằng và ngưỡng thời gian

Slider “Mức ưu tiên công bằng” $φ$ từ 0.0 (nhanh cho cả nhóm) tới 1.0 (công bằng nhất), bước 0.1, mặc định 0.5.

Quy tắc tái sử dụng bảng khoảng cách khi 4 nguồn và `graph_version` không đổi:

| Thay đổi | Chạy lại Dijkstra? | Lý do |
| --- | --- | --- |
| φ, `TOP_K`, `MIN_SPACING_M` | Không | Chỉ đổi bước xếp hạng |
| Giảm `T_LIMIT` | Không | Lọc lại bảng hiện có |
| Tăng `T_LIMIT` | **Có** | Bảng đã bị cắt tại cutoff cũ |
| Di chuyển bất kỳ vị trí nào | Có (cho nguồn đó) | Nguồn mới |

Bảng khoảng cách được cache theo khóa ($graph_{version}$, nguồn đã snap, cutoff), thời gian sống ngắn, không ghi xuống đĩa (NFR-04).

## 5. Thiết kế thuật toán

Thuật toán cơ sở của MVP là K lần Dijkstra có cutoff rồi quét toàn bộ ứng viên. Biến thể dừng sớm ở mục 5.4 cho kết quả giống hệt và chỉ được bật sau khi qua TC-16.

### 5.1. Pipeline

1. **Validate input**: số lượng, miền giá trị, nằm trong `AOI`.
2. **Snap**: tìm cạnh, $θᵢ$, $rᵢ$, $aᵢ$ (FR-03).
3. **Overlay**: tạo nguồn tạm $sᵢ$ và cạnh ra của chúng trên lớp phủ của request.
4. **K × Dijkstra** với cutoff `T_LIMIT − aᵢ` → `dist_i`, `pred_i`.
5. **Đánh giá ứng viên**: giao các `dist_i`, lọc `AOI`, tính $Tᵢ$ và $Score_φ$.
6. **Xếp hạng + đa dạng không gian** (FR-06).
7. **Dựng tuyến** cho tối đa 5 điểm được chọn (FR-07).
8. **Trả kết quả** kèm `graph_version` và thời gian từng bước.

### 5.2. Pseudocode

```python
def owa_weights(phi, K):
    beta = 1.0 - 0.9 * phi
    raw = [beta ** k for k in range(K)]
    s = sum(raw)
    return [x / s for x in raw]          # w1 >= w2 >= ... > 0, tổng = 1

def q(x):                                 # lượng tử 0.1 s
    return round(10 * x) / 10

def find_meeting_points(graph, origins, cfg):
    snaps = [snap_to_road(graph, o, cfg.snap_max_m) for o in origins]
    overlay = RequestOverlay(graph, snaps)            # không sửa graph

    dist, pred = [], []
    for s in snaps:
        d, p = dijkstra(overlay, s.source,
                        weight="travel_time",
                        cutoff=cfg.t_limit - s.access_seconds)
        dist.append(d); pred.append(p)

    w = owa_weights(cfg.phi, len(snaps))
    candidates = []
    for v in graph.original_nodes_in_aoi:          # không gồm nguồn tạm
        if any(v not in d for d in dist):
            continue
        T = [q(s.access_seconds + d[v]) for s, d in zip(snaps, dist)]
        Ts = sorted(T, reverse=True)
        score = q(sum(wk * tk for wk, tk in zip(w, Ts)))
        candidates.append(Candidate(v, T, score,
                                    t_max=Ts[0], t_avg=q(sum(T) / len(T))))

    candidates.sort(key=lambda c: (c.score, c.t_max, c.t_avg, c.node_id))

    selected = []
    for c in candidates:
        if all(planar_dist(c, s) >= cfg.min_spacing_m for s in selected):
            selected.append(c)
            if len(selected) == cfg.top_k:
                break

    for c in selected:
        c.routes = [build_route(overlay, pred[i], snaps[i], c.node_id)
                    for i in range(len(snaps))]
    return selected
```

Đây là mã minh họa luồng xử lý. `snap_to_road` phải tạo cạnh ra đúng chiều theo mục 3.3; `build_route` phải dùng đúng key cạnh trong `pred`.

### 5.3. Độ phức tạp

Với V node, E cạnh, K nguồn, binary heap:

| Bước | Thời gian | Ghi chú |
| --- | --- | --- |
| Snapping | $O(K · \log E)$ | Truy vấn STRtree |
| K × Dijkstra | $O(K · (E + V) · \log V)$ | Fibonacci heap cho $O(K · (E + V \log V))$, không cần trong thực tế vì đồ thị đường thưa |
| Đánh giá ứng viên | $O(V · K \log K)$ | Sắp 4 phần tử mỗi node |
| Sắp xếp | $O(V log V)$ | Có thể thay bằng heap và lấy dần |
| Đa dạng không gian | $O(m · TOP_K)$ | $m =$ số ứng viên phải duyệt tới khi đủ $TOP_K$ |
| Dựng tuyến | $O(TOP_K · K · L)$ | $L =$ số cạnh trên tuyến |

Bộ nhớ: $O(E + V)$ cho đồ thị cộng $O(K · V)$ cho `dist` và `pred`, chưa tính hình học.

### 5.4. Tối ưu hiệu năng

**A — Tiền xử lý đồ thị.** Đồ thị dựng offline, nạp vào bộ nhớ khi khởi động, không truy vấn OSM khi xử lý request.

**B — Cutoff theo từng nguồn.** `T_LIMIT − aᵢ` (mục 3.5).

**C — Tái sử dụng bảng khoảng cách** theo bảng ở FR-09.

**D — Biểu diễn mảng.** Chuyển đồ thị sang CSR (mảng chỉ số liên tục) và chạy Dijkstra bằng `scipy.sparse.csgraph` hoặc thư viện C/Rust. Chạy K nguồn song song nếu tài nguyên cho phép. NetworkX chỉ dùng để tham chiếu đúng đắn trong test.

**E — Dựng tuyến lười.** Chỉ dựng hình học cho điểm được chọn.

**F — Dijkstra đồng bộ có dừng sớm (chính xác).** Chạy K hàng đợi cùng lúc. Mỗi bước lấy phần tử có $aᵢ$ + khóa nhỏ nhất trong K hàng đợi; giá trị đó là mốc thời gian t, không giảm theo thời gian chạy.

- Node được cả K nguồn chốt thì tính Score và đưa vào heap ứng viên theo thứ tự xếp hạng.
- Node chưa được nguồn i chốt có $Tᵢ ≥ t$, nên $T_{max} ≥ t$ và theo tính chất 5 ở mục 3.4 thì $Score ≥ w₁ · t$.$
- Vì vậy ứng viên đầu heap với $$q(Score) < w₁ · t − 0.1 s$ (biên an toàn cho sai số lượng tử) đã ở đúng vị trí cuối cùng trong thứ tự xếp hạng và có thể đưa qua bước đa dạng ngay.
- Dừng khi đã chọn đủ $TOP_K$, hoặc khi mọi hàng đợi chạm cutoff (khi đó xả nốt heap ứng viên theo thứ tự).

Kết quả trùng với thuật toán cơ sở, kể cả bước đa dạng tham lam. Hiệu quả cao khi $φ$ lớn ($w₁$ gần 1) và 4 người ở gần nhau; khi $φ = 0, w₁ = 0.25$ nên cận yếu. Khi bật F, cache ở C phải lưu trạng thái hàng đợi để tiếp tục mở rộng khi $φ$ giảm.

**G — Nghiên cứu sau MVP:** cận dưới theo từng node (dùng giá trị đã chốt của các nguồn đã tới) để làm chặt điều kiện dừng; Contraction Hierarchies kèm truy vấn one-to-many (PHAST, RPHAST); Dijkstra theo cạnh cho cấm rẽ. Mọi thay thế phải qua TC-16 so với thuật toán cơ sở.

## 6. Cấu trúc dữ liệu

Các giá trị dưới đây là dữ liệu giả lập, nhưng tự nhất quán về mặt số học.

### 6.1. Graph Node

```json
{
  "id": 100234,
  "latitude": 21.0285,
  "longitude": 105.8542,
  "x_utm": 588412.3,
  "y_utm": 2327115.8,
  "highway": "traffic_signals",
  "in_aoi": true
}
```

### 6.2. Graph Edge

```json
{
  "id": "100234-100235-0",
  "source": 100234,
  "target": 100235,
  "key": 0,
  "length_m": 220.5,
  "road_type": "residential",
  "oneway": true,
  "estimated_speed_kmh": 25,
  "travel_time_seconds": 31.752,
  "geometry": "LineString (EPSG:32648)"
}
```

Kiểm tra: $220.5 m ÷ (25 / 3.6) m/s = 31.752 s.$

### 6.3. Snapped Origin

```json
{
  "id": "A",
  "input": {"lat": 21.0285, "lon": 105.8542},
  "edge_id": "100234-100235-0",
  "theta": 0.37,
  "snap_distance_m": 42.0,
  "access_seconds": 30.0,
  "snapped": {"lat": 21.02862, "lon": 105.85401}
}
```

Kiểm tra: $42.0 m ÷ 1.4 m/s = 30.0 s.$

### 6.4. Meeting Candidate

```json
{
  "node_id": 100234,
  "location": {"lat": 21.0285, "lon": 105.8542},
  "travel_times_seconds": {"A": 720.0, "B": 840.0, "C": 780.0, "D": 660.0},
  "access_seconds": {"A": 30.0, "B": 0.0, "C": 12.5, "D": 48.0},
  "max_time_seconds": 840.0,
  "min_time_seconds": 660.0,
  "difference_seconds": 180.0,
  "avg_time_seconds": 750.0,
  "phi": 0.5,
  "score_seconds": 790.8
}
```

`travel_times_seconds` đã gồm `access_seconds`. Kiểm tra Score: $0.4953·840 + 0.2724·780 + 0.1498·720 + 0.0824·660 ≈ 790.8 s.$

## 7. Thiết kế API

### 7.1. POST /api/v1/meeting-points

**Request**

```json
{
  "origins": [
    {"id": "A", "lat": 21.0285, "lon": 105.8542},
    {"id": "B", "lat": 21.0341, "lon": 105.8123},
    {"id": "C", "lat": 21.0120, "lon": 105.8242},
    {"id": "D", "lat": 21.0452, "lon": 105.8418}
  ],
  "travel_mode": "car",
  "optimization": {
    "phi": 0.5,
    "max_travel_seconds": 3600,
    "top_k": 5,
    "min_spacing_meters": 500
  }
}
```

Ràng buộc: đúng 4 `origins`, `id` duy nhất; `phi` ∈ [0, 1]; `max_travel_seconds` ∈ [300, 7200]; `top_k` ∈ [1, 5]; `min_spacing_meters` ∈ [0, 5000]. Tọa độ chỉ mang tính minh họa.

**Response**

```json
{
  "request_id": "req_001",
  "graph_version": "hanoi-osm-v1",
  "weight_profile_version": "car-v1",
  "status": "success",
  "unit": "seconds",
  "objective": {"type": "owa_geometric", "phi": 0.5,
                "weights": [0.4953, 0.2724, 0.1498, 0.0824]},
  "origins": [
    {"id": "A", "snap_distance_m": 42.0, "access_seconds": 30.0,
     "snapped": {"lat": 21.02862, "lon": 105.85401}}
  ],
  "results": [
    {
      "rank": 1,
      "node_id": 100234,
      "location": {"lat": 21.0285, "lon": 105.8542},
      "travel_times": {"A": 720.0, "B": 840.0, "C": 780.0, "D": 660.0},
      "max_time": 840.0,
      "min_time": 660.0,
      "difference": 180.0,
      "avg_time": 750.0,
      "score": 790.8,
      "routes": {
        "A": {
          "network_seconds": 690.0,
          "access_seconds": 30.0,
          "duration_seconds": 720.0,
          "distance_meters": 3400,
          "geometry": {"type": "LineString", "coordinates": []}
        }
      }
    }
  ],
  "timings_ms": {"snap": 3, "dijkstra": 410, "scan": 60,
                 "rank": 12, "routes": 25, "total": 520}
}
```

Trong dữ liệu thật, `origins` và `routes` có đủ A–D; `coordinates` là mảng GeoJSON `[longitude, latitude]`. Mọi tuyến thỏa `duration_seconds = access_seconds + network_seconds` và `duration_seconds` bằng giá trị tương ứng trong `travel_times`. `weights` được trả về để kiểm tra độc lập, frontend không dùng chúng để tính lại.

### 7.2. POST /api/v1/meeting-points/{request_id}/rerank

Xếp hạng lại từ bảng khoảng cách đã cache khi chỉ đổi `phi`, `top_k`, `min_spacing_meters` hoặc giảm `max_travel_seconds`. Nếu cache đã hết hạn hoặc `max_travel_seconds` tăng, trả `RECOMPUTE_REQUIRED` và client gọi lại 7.1.

### 7.3. GET /api/v1/map/config

Trả về: polygon `AOI`; phương tiện hỗ trợ; giới hạn tham số ở 7.1; `graph_version`, `weight_profile_version`, `source_date`; giá trị mặc định của `phi` và `v_access`.

### 7.4. Mã lỗi

| Error code | HTTP | Ý nghĩa |
| --- | --- | --- |
| INVALID\_COORDINATES | 400 | Tọa độ sai miền hoặc không phải số hữu hạn |
| INVALID\_PARAMETERS | 400 | Tham số ngoài miền cho phép |
| OUT\_OF\_COVERAGE | 422 | Vị trí ngoài `AOI` |
| SNAP\_FAILED | 422 | Không có cạnh hợp lệ trong `SNAP_MAX_M` |
| NO\_COMMON\_REACHABLE\_NODE | 200, `status: "empty"` | Không node nào thỏa mục 3.5; kèm `min_required_seconds` nếu tính được |
| RECOMPUTE\_REQUIRED | 409 | Không thể xếp hạng lại từ cache |
| GRAPH\_UNAVAILABLE | 503 | Đồ thị chưa nạp xong |
| INTERNAL\_ERROR | 500 | Lỗi không xác định |

Response lỗi có `error_code`, `message`, `request_id`. `min_required_seconds` là min theo v của maxᵢ Tᵢ(v), chỉ tính được khi Dijkstra không bị cutoff chặn; nếu bị chặn thì trả `> max_travel_seconds`.

## 8. Kiến trúc hệ thống

### 8.1. Technology Stack

| Thành phần | Công nghệ đề xuất |
| --- | --- |
| Frontend | Next.js + TypeScript |
| Map Rendering | MapLibre GL JS |
| Backend | Python + FastAPI |
| Xây đồ thị (offline) | OSMnx + NetworkX |
| Định tuyến (online) | CSR arrays + `scipy.sparse.csgraph` (hoặc thư viện C/Rust tương đương) |
| Geospatial | Shapely + GeoPandas + pyproj (EPSG:4326 ↔ EPSG:32648) |
| Spatial Index | Shapely STRtree |
| Map Dataset | OpenStreetMap |
| Storage | GraphML / GeoPackage + file CSR `.npz` có phiên bản |
| Cache | In-memory LRU có TTL; Redis nếu chạy nhiều instance |
| Deployment | Docker |

NetworkX được giữ làm bản cài đặt tham chiếu trong test (TC-01, TC-16), không dùng trên đường xử lý request.

### 8.2. Backend Modules

```text
backend/
├── app/
│   ├── main.py
│   ├── api/
│   │   └── meeting.py
│   ├── services/
│   │   ├── graph_loader.py
│   │   ├── coordinate_snapper.py     # chiếu, STRtree, θ, offset
│   │   ├── request_overlay.py        # nguồn tạm, không sửa đồ thị chung
│   │   ├── shortest_path.py
│   │   ├── objective.py              # trọng số OWA, lượng tử, thứ tự xếp hạng
│   │   ├── meeting_optimizer.py
│   │   └── route_builder.py
│   ├── models/
│   │   ├── requests.py
│   │   └── responses.py
│   └── config/
│       ├── settings.py
│       └── speed_profiles/car-v1.yaml
├── scripts/
│   ├── download_osm.py
│   ├── build_graph.py                # SCC, chia cạnh dài, CSR
│   └── validate_graph.py             # thống kê τ(e), kiểm tra vùng đệm
├── data/
└── tests/
```

### 8.3. Frontend Modules

```text
frontend/
├── app/
├── components/
│   ├── MapView.tsx
│   ├── OriginMarker.tsx
│   ├── SnapIndicator.tsx       # đoạn nối vị trí gốc → điểm snap
│   ├── MeetingMarker.tsx
│   ├── RouteLayer.tsx
│   ├── FairnessSlider.tsx      # φ ∈ [0, 1]
│   └── ResultsPanel.tsx
├── services/
│   └── meetingApi.ts
├── types/
└── utils/
```

## 9. Thiết kế giao diện

### 9.1. Màn hình chính

**Map View — khoảng 70% chiều rộng:** bản đồ Hà Nội; ranh giới `AOI`; 4 marker xuất phát khác màu, kèm đoạn nối tới điểm snap khi $rᵢ > 30 m$; marker kết quả đánh số 1–5; tuyến của từng người tới điểm đang chọn, bật/tắt được theo người.

**Control Panel — khoảng 30% chiều rộng:**

- Danh sách 4 người, tọa độ và khoảng cách snap.
- Nút chọn lại vị trí.
- Slider “Mức ưu tiên công bằng” $φ,$ hai đầu ghi “Nhanh cho cả nhóm” và “Công bằng nhất”.
- Giới hạn thời gian di chuyển.
- Nút Find Meeting Points.
- Danh sách kết quả theo mẫu FR-08, nhãn “thời gian ước lượng”.

### 9.2. User Flow

1. Mở web app.
2. Đặt vị trí A, B, C, D (thứ tự tùy ý).
3. Chỉnh $φ$ và giới hạn thời gian nếu muốn.
4. Bấm “Find Meeting Points” → backend xử lý.
5. Xem tối đa 5 điểm gặp.
6. Chọn một điểm → xem 4 tuyến.
7. Kéo slider $φ$ → danh sách cập nhật qua endpoint rerank, không chạy lại Dijkstra.

### 9.3. Trạng thái UI

| Trạng thái | Điều kiện |
| --- | --- |
| `idle` | Chưa đủ 4 vị trí |
| `ready` | Đủ đầu vào, có thể tính |
| `loading` | Backend đang xử lý |
| `success` | Có ít nhất một điểm gặp |
| `empty` | Không có điểm hợp lệ; hiển thị gợi ý tăng giới hạn thời gian |
| `stale` | Vị trí đã đổi sau lần tính; kết quả cũ làm mờ và ghi “chưa cập nhật” |
| `error` | Lỗi dữ liệu hoặc hệ thống |

## 10. Xử lý dữ liệu bản đồ

### 10.1. Data Preparation (offline)

1. Xác định `AOI` bằng GeoJSON Polygon; tạo `ROUTING_AREA` = buffer `BUFFER_M` tính trên EPSG:32648.
2. Tải mạng đường OSM của `ROUTING_AREA` (OSMnx, `network_type="drive"`).
3. Dựng MultiDiGraph có hướng; chiếu toàn bộ hình học sang EPSG:32648.
4. Tính lại $ℓ(e)$ từ hình học đã chiếu.
5. Gán $v(e)$ từ bảng tốc độ có phiên bản, áp cận trên `maxspeed`; tính $τ(e)$. Kiểm tra $τ(e) > 0$ và hữu hạn với mọi cạnh.
6. **Giữ thành phần liên thông mạnh lớn nhất**; ghi lại số node và cạnh bị loại, có bản đồ các vùng bị loại nằm trong `AOI` để rà soát thủ công.
7. Chia các cạnh có $τ(e) >$ `MAX_EDGE_SECONDS` thành đoạn đều nhau (mục 3.7).
8. Gắn cờ `in_aoi` cho từng node.
9. Dựng STRtree trên hình học cạnh và xuất mảng CSR.
10. Chạy `validate_graph.py`: thống kê $τ(e)$ (P50, P99, max), kiểm tra vùng đệm (TC-15), so sánh một mẫu tuyến với NetworkX.
11. Lưu đồ thị có phiên bản; backend nạp khi khởi động.

### 10.2. Đường một chiều và cấm rẽ

**Đường một chiều:** hệ thống chỉ đi theo chiều cạnh, kể cả cạnh ra của nguồn tạm (mục 3.3).

**Cấm rẽ** phụ thuộc cặp (cạnh vào, cạnh ra) nên Dijkstra trên node không xử lý được. Trong MVP:

- Chỉ bảo đảm tuân theo hướng cạnh đã nạp; không tuyên bố tuyến tuân thủ cấm rẽ.
- Bản dùng thực tế phải chuyển sang Dijkstra theo cạnh: trạng thái là cạnh đi vào, chuyển tiếp có chi phí rẽ $c(e_{in}, e_{out}) ≥ 0$, bằng $+∞$ với cặp bị cấm. Thời gian tới node v là min theo các cạnh vào $v$. Mọi tính chất của mục 3.4 và 5.4 F vẫn giữ nguyên vì chúng chỉ dùng vector $Tᵢ(v)$.

### 10.3. Đèn giao thông

OSM có thể có vị trí đèn nhưng không đầy đủ và không có pha thời gian thực. MVP không dự đoán pha đèn. Phiên bản sau có thể cộng phụ phí chờ cố định vào chi phí rẽ ở 10.2, với điều kiện bảng tốc độ chưa phản ánh thời gian chờ đó (tránh tính hai lần).

### 10.4. Versioning

Mỗi phiên bản đồ thị lưu: `graph_version`, `source`, `source_date`, `build_date`, `area_id`, `buffer_m`, `crs`, `travel_mode`, `node_count`, `edge_count`, `scc_removed_nodes`, `max_edge_seconds`, `tau_p50`, `tau_p99`, `tau_max`, `weight_profile_version`. Mỗi response ghi `graph_version` và `weight_profile_version` để kết quả tái tạo được.

## 11. Yêu cầu phi chức năng

### NFR-01: Performance

- Mục tiêu kiểm thử: P95 thời gian xử lý $≤ 5 s$ cho request mới và $≤ 300 ms$ cho rerank, trên môi trường benchmark được xác định. Đây là tiêu chí kiểm thử, chưa phải cam kết.
- Đồ thị nạp sẵn trước khi nhận request; không tải OSM khi xử lý request.
- Đo riêng snap, Dijkstra, quét ứng viên, xếp hạng, dựng tuyến (trả trong `timings_ms`).

### NFR-02: Accuracy

- $δᵢ(v)$ khớp tổng τ của tuyến trả về trong sai số mục 3.6.
- Thuật toán tối ưu hóa (CSR, dừng sớm) cho kết quả trùng bản tham chiếu NetworkX (TC-16).
- Không dùng khoảng cách đường chim bay thay khoảng cách mạng đường, ngoại trừ offset tiếp cận $aᵢ$ và khoảng cách tách biệt giữa kết quả, vốn được định nghĩa là hình học.
- Mọi khoảng cách hình học tính trên EPSG:32648.
- Không giả định đường hai chiều khi dữ liệu chỉ cho một chiều.
- Hiển thị “thời gian ước lượng”, không gọi là ETA.

### NFR-03: Reliability

- Không sửa đồ thị dùng chung; nguồn tạm nằm trên lớp phủ của request (TC-13).
- Xử lý trường hợp không có ứng viên và snap thất bại bằng mã lỗi ở 7.4.
- Giao diện không bị treo khi backend lỗi hoặc chậm.

### NFR-04: Privacy

- Không yêu cầu tài khoản.
- Không lưu tọa độ lâu dài; cache bảng khoảng cách chỉ trong bộ nhớ, TTL mặc định 15 phút.
- Log không chứa tọa độ chính xác; nếu cần thì làm tròn tới 2 chữ số thập phân (khoảng 1 km).
- HTTPS khi triển khai công khai; giới hạn tần suất request.

### NFR-05: Licensing

- Ghi công OpenStreetMap theo yêu cầu.
- Kiểm tra điều kiện ODbL với việc dùng, chia sẻ, phân phối dữ liệu dẫn xuất.
- Dùng tile provider có điều khoản phù hợp; không giả định dịch vụ tile công cộng là không giới hạn.

## 12. Testing Strategy

### 12.1. Unit Tests

| ID | Tên | Đầu vào | Kỳ vọng |
| --- | --- | --- | --- |
| TC-01 | Dijkstra correctness | Đồ thị mẫu nhỏ có đáp án | δ đúng từng node, kể cả có cạnh song song |
| TC-02 | One-way | Chỉ có cạnh $u → v$ | $v$ tới được từ $u$; $u$ không tới được từ $v$ |4
| TC-03 | Scoring | $T = (10, 12, 11, 10)$ | $φ = 0: 10.750; φ = 0.5: 11.263; φ = 1: 11.890$ (sai số 0.001) |
| TC-04 | Unreachable | Một nguồn không tới được $v$ trong cutoff | $v$ bị loại |
| TC-05 | Coincident origins | 4 nguồn trùng một node, $aᵢ = 0$ | Hạng 1 là node đó, $Score = 0$ |
| TC-06 | Route consistency | Mọi kết quả trả về | $Στ$ của tuyến $= δᵢ(v)$ trong sai số mục 3.6 |
| TC-07 | Stable ranking & symmetry | Cùng request chạy 2 lần; hoán đổi nhãn A–D | Thứ tự giống hệt; tập điểm và Score không đổi khi hoán đổi nhãn |
| TC-08 | Pareto monotonicity | 10 000 cặp vector ngẫu nhiên $u ≤ v$ (ít nhất một thành phần chặt); ví dụ $P/Q$ ở mục 3.4 | $Score(u) < Score(v)$ với mọi $φ ∈ {0, 0.1, …, 1}$; $P$ xếp trên $Q$ |
| TC-09 | Fairness transfer | Chuyển ε từ người xa hơn sang người gần hơn, không đảo thứ tự | Score không tăng; giảm chặt khi $φ > 0$ |
| TC-10 | Bounds | Vector ngẫu nhiên | $T_{avg} ≤ Score ≤ T_{max}$; $φ = 0$ cho $Score = T_{avg}$ |
| TC-11 | Snap split | Điểm tại $θ = 0.3$ trên cạnh hai chiều $τ = 100 s$ và trên cạnh một chiều $τ = 100 s$ | Hai chiều: $s → w \quad 70 s, s → u \quad 30 s$. Một chiều: chỉ $s → w \quad 70 s$ |
| TC-12 | Access offset | Cùng cạnh, $rᵢ = 0$ và $rᵢ = 70 m$ | $Tᵢ$ chênh đúng 50 s với mọi node |
| TC-13 | Shared graph immutability | 50 request đồng thời | Hash đồ thị chung trước và sau bằng nhau |
| TC-14 | Cutoff reuse | Chạy với `T_LIMIT` $= 900 s$ rồi tăng lên $1800 s$ | Rerank báo `RECOMPUTE_REQUIRED`; kết quả tính lại trùng chạy mới với $1800 s$ |
| TC-15 | Buffer sensitivity | 200 cặp trong dải 1 km sát biên | $≥ 99%$ cặp lệch ≤ 1% giữa `BUFFER_M` và $2 ×$ `BUFFER_M` |
| TC-16 | Optimized equivalence | 1 000 request ngẫu nhiên trên đồ thị thật | Kết quả CSR và dừng sớm trùng bản tham chiếu NetworkX: cùng node, cùng thứ tự, Score lệch ≤ 0.1 s |

### 12.2. Integration Tests

- Dữ liệu thật của một khu vực thử nghiệm tại Hà Nội.
- Snapping: trường hợp gần nút giao, gần cầu vượt (nguy cơ snap nhầm tầng), đường một chiều.
- Tuyến đúng chiều cạnh; vị trí hiển thị đúng.
- Đối chiếu một mẫu tuyến với hệ thống định tuyến độc lập để ước lượng sai lệch do tốc độ và cấm rẽ; ghi lại sai lệch của Delta, không chỉ của từng thời gian.

### 12.3. Performance Tests

Kịch bản: 4 nguồn gần nhau; xa nhau; sát ranh giới; truy vấn liên tiếp; nhiều request đồng thời; rerank liên tục khi kéo slider.

Ghi nhận: `graph_load_time`, `snap_time`, `dijkstra_time`, `candidate_scan_time`, `ranking_time`, `route_build_time`, `total_response_time`, `rerank_time`, `peak_memory_usage`, số node đã mở rộng mỗi nguồn.

## 13. Rủi ro kỹ thuật

| Rủi ro | Mức độ | Phương án xử lý |
| --- | --- | --- |
| Dữ liệu OSM không đầy đủ | Cao | Rà soát khu thử nghiệm; bản đồ các vùng bị loại bởi SCC |
| Không xử lý cấm rẽ và chi phí rẽ | Cao | Dijkstra theo cạnh (10.2); đo sai lệch Delta trong integration test |
| Điểm gặp nằm tại nút giao nguy hiểm | Cao | Cảnh báo; bảng loại trừ node (mục 3.5 điều kiện 4) |
| Snap vào sai nhánh đường hoặc sai tầng | Cao | Chỉ snap vào SCC; hiển thị điểm snap để người dùng kéo lại |
| Chọn sai tham số công bằng mặc định | Trung bình | Thử nghiệm người dùng với $φ ∈ {0.3, 0.5, 0.7}$; $φ$ là cấu hình |
| Tốc độ ước lượng sai | Trung bình | Hiệu chỉnh bảng tốc độ có phiên bản; so với ETA API |
| Offset tiếp cận sai do ngõ nhỏ không có trong đồ thị | Trung bình | $v_{access}$ là cấu hình; cân nhắc nạp thêm `service` roads |
| Đồ thị lớn, phản hồi chậm | Trung bình | CSR, cutoff, cache, dừng sớm (5.4 F) |
| Vùng đệm quá hẹp | Trung bình | TC-15 |
| 5 kết quả quá gần nhau | Trung bình | Đa dạng không gian (FR-06) |
| Không có điểm nào trong ngưỡng | Thấp | Gợi ý `min_required_seconds` |
| Dữ liệu thay đổi theo thời gian | Trung bình | Versioning và cập nhật định kỳ |

## 14. Kế hoạch phát triển

Mỗi phase có điều kiện qua cổng trước khi sang phase sau.

### Phase 1 — Graph Prototype (chỉ Python, chưa cần frontend)

- Dữ liệu một khu thử nghiệm; đồ thị có hướng, lọc SCC, chia cạnh dài, chiếu EPSG:32648.
- Snapping có offset; 4 lần Dijkstra; hàm OWA; xếp hạng và đa dạng.
- Bản tham chiếu NetworkX.

**Cổng:** TC-01 đến TC-12 đạt.

### Phase 2 — Web MVP

- Bản đồ tương tác, 4 marker, hiển thị điểm snap.
- API 7.1–7.3, cache và rerank.
- Hiển thị Top 5 và 4 tuyến; slider $φ$; xử lý lỗi.
- Chuyển định tuyến sang CSR.

**Cổng:** TC-13 đến TC-16 đạt; benchmark NFR-01 có số liệu; toàn bộ mục 15.

### Phase 3 — Routing Quality

- Dijkstra theo cạnh với cấm rẽ và chi phí rẽ.
- Xe máy với bộ quy tắc riêng.
- Hiệu chỉnh bảng tốc độ và $v_{access}$.
- Bảng loại trừ node không phù hợp làm điểm dừng.
- Bật dừng sớm (5.4 F) sau khi TC-16 đạt trên đồ thị theo cạnh.

### Phase 4 — Intelligent Meeting Points

- Điểm gặp giữa cạnh (bài toán tâm tuyệt đối trên mạng).
- Vùng gặp tối ưu thay vì một số node; gợi ý địa điểm thực tế gần vùng đó.
- Trọng số theo giờ và thời điểm xuất phát; nhiều phương tiện trong một nhóm.

## 15. Acceptance Criteria cho MVP

- [ ] Người dùng đặt được chính xác 4 vị trí trong `AOI`.
- [ ] Tọa độ được xác thực, snap vào SCC, có offset tiếp cận hiển thị trên UI.
- [ ] Backend xử lý 4 nguồn trên đồ thị có hướng mà không sửa đồ thị chung (TC-13).
- [ ] Dijkstra đúng trên bộ test chuẩn (TC-01, TC-02).
- [ ] Xếp hạng đúng công thức OWA và thứ tự toàn phần ở mục 3.6 (TC-03, TC-07).
- [ ] Không điểm nào được xếp trên một điểm trội hơn nó (TC-08).
- [ ] Điểm gặp trả về dưới dạng tọa độ GPS, tối đa 5 điểm, cách nhau ≥ 500 m.
- [ ] Mỗi điểm hiển thị được 4 tuyến, tổng τ khớp thời gian xếp hạng (TC-06).
- [ ] Đổi φ làm đổi xếp hạng khi dữ liệu cho phép, không chạy lại Dijkstra.
- [ ] Tăng giới hạn thời gian thì tính lại đúng (TC-14).
- [ ] Không có điểm hợp lệ thì hiển thị trạng thái `empty` kèm gợi ý.
- [ ] Không yêu cầu dữ liệu quán ăn hay quán cà phê.
- [ ] Giao diện ghi rõ đây là thời gian di chuyển ước lượng.
- [ ] Không có tuyến nào đi ngược chiều cạnh đã khai báo.
- [ ] Vùng đệm đạt TC-15; báo cáo τ(e) P50/P99/max có trong metadata đồ thị.
- [ ] Có benchmark hiệu năng trên dữ liệu thật.
- [ ] Có ghi công OpenStreetMap.

## 16. Các quyết định cần review

| ID | Vấn đề | Đề xuất | Phương án thay thế |
| --- | --- | --- | --- |
| D-01 | Tiêu chí chính | Thời gian di chuyển | Quãng đường |
| D-02 | Phương tiện MVP | Ô tô, sau đó xe máy | Xe máy ngay từ MVP |
| D-03 | Địa điểm ứng viên | Node OSM, cạnh dài được chia ≤ 60 s | Điểm giữa cạnh (Phase 4) |
| D-04 | Thuật toán | K lần Dijkstra có cutoff; dừng sớm ở Phase 3 | CH + one-to-many |
| D-05 | Hàm mục tiêu | OWA trọng số hình học, $φ ∈ [0, 1]$, mặc định 0.5 | Trung bình lũy thừa $(Σ Tᵢᵖ / K)^{(1/p)}$ với $p ∈ [1, 8]$; leximax |
| D-06 | Giới hạn thời gian | 60 phút/người, đã gồm offset tiếp cận | Không gồm offset |
| D-07 | Số kết quả | Top 5 | Top 3 |
| D-08 | Khoảng cách giữa kết quả | ≥ 500 m Euclid trên EPSG:32648; không nới | Khoảng cách theo mạng đường |
| D-09 | Phạm vi | Polygon nội đô, vùng đệm 3 km | Vùng đệm lớn hơn nếu TC-15 không đạt |
| D-10 | Tắc đường real-time | Hoãn | — |
| D-11 | Backend | Python FastAPI + CSR | Routing engine riêng (OSRM, Valhalla) |
| D-12 | Dữ liệu đường | OpenStreetMap | — |
| D-13 | Điểm gặp giữa cạnh | Hoãn; sai số bị chặn bởi max τ(e) | — |
| D-14 | Cấm rẽ đầy đủ | Bắt buộc trước khi dùng như công cụ chỉ đường | — |
| D-15 | Offset tiếp cận | $aᵢ = rᵢ / 1.4 m/s$ | Bỏ qua; hoặc tốc độ theo loại ngõ |
| D-16 | Bước lượng tử | 0.1 s | 1 s |

D-05 là quyết định sản phẩm quan trọng nhất. Cả OWA và trung bình lũy thừa đều đơn điệu, Schur-lồi và cùng đơn vị giây; OWA được chọn vì trọng số có thể hiển thị trực tiếp và cho cận dừng sớm đơn giản. Nếu nhóm cố ý muốn phạt việc có người đến quá sớm (như công thức v0.1.0), điều đó phải ghi thành quyết định riêng và áp dụng sau bước lọc Pareto.

## 17. Kết luận

W2M tìm điểm gặp bằng cách kết hợp **đường đi ngắn nhất từ nhiều nguồn** với **một hàm tổng hợp đơn điệu và công bằng**, và không cần biết trước đích đến:

1. Mỗi người được snap vào mạng đường, kèm offset tiếp cận.
2. Mỗi người tạo một bản đồ thời gian ngắn nhất bằng Dijkstra có cutoff.
3. Mỗi node chung được đánh giá bằng OWA trên vector thời gian đã sắp xếp.
4. Ứng viên được xếp theo thứ tự toàn phần, lọc đa dạng không gian, rồi dựng tuyến.

So với v0.1.0, pipeline không đổi nhưng ba bảo đảm toán học được thêm: điểm hạng 1 luôn Pareto-tối ưu, sai số do chỉ xét node bị chặn bởi max τ(e), và mọi tối ưu hiệu năng phải cho kết quả trùng bản tham chiếu. Giả định lớn nhất còn lại là việc bỏ qua chi phí và cấm rẽ, được xử lý ở Phase 3.
