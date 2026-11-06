# Chuẩn hóa hình học cạnh trên EPSG:32648

**Date:** 2026-11-06 16:53  
**Status:** Completed

## Summary

Bổ sung bước hình học offline M1 từ snapshot OSM đã có, làm đầu vào cho tính trọng số và dựng tuyến.

## Changes Made

- Chiếu node/cạnh sang EPSG:32648; giữ lon/lat gốc, chuẩn hóa geometry theo chiều nguồn → đích.
- Tạo geometry khi thiếu, giữ đường cong/cạnh song song; tính lại length_m và length bằng mét.
- Báo lỗi dữ liệu không hợp lệ; xử lý trên bản sao, không sửa snapshot gốc.
- CLI kiểm tra checksum, xuất GraphML/metadata riêng sau kiểm tra nạp lại.

## Files Affected

- `backend/app/services/graph_geometry.py` — xử lý hình học.
- `backend/scripts/prepare_graph_geometry.py` — CLI offline và provenance.
- `backend/tests/test_graph_geometry.py` — 22 test mới.
- `backend/data/README.md`, `docs/plans/W2M-MVP-Plan.md` — hướng dẫn và checklist.

## Technical Decisions

- Chỉ chấp nhận WGS84 đầu vào; geometry phải khớp đầu mút trong 0,01 m.
- Đồng bộ length với length_m để tránh dùng lại chiều dài cũ.

## Verification

- **Tests:** 94 test backend đạt, gồm roundtrip OSMnx; không có test bỏ qua.
- **Build/Lint/Typecheck:** Ruff đạt; không chạy frontend build/typecheck vì không thay frontend.
- **Manual Verification:** CLI chạy offline trên snapshot thật, giữ 21.129 node/36.912 cạnh; chiều dài 0,094–1.170,781 m. GraphML nạp lại đạt kiểm tra.

## Known Issues / Limitations

- 18 cảnh báo deprecation Shapely/TestClient; chưa phải đồ thị production.
- Chưa gán trọng số, lọc SCC, chia cạnh hoặc xuất CSR.

## Next Steps

- Cài speed profile và parser maxspeed, tính thời gian cạnh.
