# Chia cạnh theo thời gian và biên AOI

**Date:** 2026-11-07 18:11  
**Status:** Completed

## Summary

Đã chia graph SCC thành các cạnh không quá 60 giây, đồng bộ điểm chia hai chiều
và cắt tại biên AOI. Giữ chiều đi, đường cong, tổng chiều dài và thời gian cạnh gốc.

## Changes Made

- Chia theo chiều chậm hơn của cặp đã ghép; đường khác không dùng chung node mới.
- Xử lý biên ngoài, lỗ, tiếp xúc và đoạn trùng biên; phân loại aoi_relation.
- Cấp ID tất định, xuất lineage và mapping reverse mới, kiểm tra SCC và GraphML reload.
- CLI kiểm tra checksum và công bố artifact qua staging; không đổi dữ liệu nguồn.

## Files Affected

- `backend/app/services/graph_split.py` — chia cạnh và kiểm tra bảo toàn.
- `backend/scripts/prepare_graph_split.py` — CLI, provenance và artifact.
- `backend/tests/test_graph_split.py` — 30 test mới.
- `README.md`, `backend/data/README.md`, `docs/plans/W2M-MVP-Plan.md` — hướng dẫn và checklist.

## Technical Decisions

- Node sinh thêm dùng ID âm giảm dần theo nhóm cạnh đã sắp; child giữ key chiều gốc.
- Chỉ chia chung cặp có geometry đảo chính xác; không dịch chuyển cặp khớp xấp xỉ.
- Dùng biên số học khi tính số đoạn, phần dư thời gian đặt ở đoạn cuối.
- Phân loại biên sai số 1e-7 m; chưa gắn cờ ứng viên.

## Verification

- **Tests:** toàn bộ 253 test backend đạt, không bỏ qua; 54 cảnh báo deprecation.
- **Build/Lint/Typecheck:** Ruff đạt; không chạy frontend build/typecheck vì không đổi frontend.
- **Manual Verification:** CLI tạo `backend/data/split/drive-20261106T092834Z-car-v1-split-v1/`:
  20.221 node/35.556 cạnh, thêm 59 node, chia 82 cạnh gốc, max 56,177981 giây.
  Kiểm tra checksum, lineage đủ 35.466 cạnh gốc, geometry và mọi giao biên đạt;
  sai số chiều dài tối đa 2,274e-13 m, thời gian không đổi. Seed 20261107, 20 nguồn
  tới 20.162 node gốc: 403.240 khoảng cách lệch tối đa 4,548e-13 giây.
  Môi trường Python 3.12.13, NetworkX 3.7, Shapely 2.2.0, OSMnx 2.1.1;
  working tree trên commit nền `fde8a43`.

## Known Issues / Limitations

- Cặp mơ hồ hoặc geometry chỉ khớp xấp xỉ cần rà soát trước khi chia chung.
- Chưa nghiệm thu AOI toàn nội đô, xuất CSR hoặc tích hợp runtime; cảnh báo deprecation còn tồn tại.

## Next Steps

- Gắn cờ ứng viên trong AOI và hỗ trợ danh sách node loại trừ.
