# Lọc SCC lớn nhất của đồ thị trọng số

**Date:** 2026-11-07 16:16  
**Status:** Completed

## Summary

Đã bổ sung bước lọc SCC offline sau gán trọng số, giữ mạng đường có thể đi tới
nhau theo chiều cạnh. Xuất graph và hình học phần bị loại trong AOI để rà soát.

## Changes Made

- Lọc SCC theo số node, bảo toàn hướng, cạnh song song, hình học và trọng số.
- CLI kiểm tra checksum/profile, xuất GraphML, AOI, profile, metadata và GeoJSON
  phần bị loại; kiểm tra nạp lại trước khi công bố thư mục mới.
- Cắt cạnh bị loại theo AOI, gồm cả cạnh có hai đầu ngoài vùng; giữ node trên biên.
- Thêm regression test cho hòa SCC, bất biến đầu vào, lỗi artifact và nạp lại.

## Files Affected

- `backend/app/services/graph_components.py` — lọc graph và tạo feature bị loại.
- `backend/scripts/prepare_graph_scc.py` — CLI, validation và xuất artifact.
- `backend/tests/test_graph_components.py` — 18 trường hợp kiểm thử.
- `backend/data/README.md`, `docs/plans/W2M-MVP-Plan.md` — lệnh chạy và checklist.

## Technical Decisions

- Hòa số node thì chọn SCC có node ID nhỏ nhất, không phụ thuộc thứ tự chèn.
- Xử lý trên bản sao, không sửa artifact weighted nguồn.
- Bỏ bộ đếm tốc độ cũ khỏi graph đã lọc vì chúng mô tả graph trước lọc.

## Verification

- **Tests:** toàn bộ 193 test backend đạt, không bỏ qua; 45 cảnh báo deprecation.
- **Build/Lint/Typecheck:** Ruff đạt; không chạy frontend build/typecheck vì không đổi frontend.
- **Manual Verification:** CLI dữ liệu Hà Nội thành công, artifact
  `backend/data/scc/drive-20261106T092834Z-car-v1-scc-v2/` giữ 20.162 node/35.466 cạnh
  từ 443 SCC; loại 967 node/1.446 cạnh. GeoJSON AOI có 29 node/37 feature cạnh.
  Đã đối chiếu checksum, liên thông mạnh, mọi thuộc tính node/cạnh giữ lại và
  tính hợp lệ geometry. Chưa xem bản đồ trực quan.

## Known Issues / Limitations

- AOI thử nghiệm; chưa đánh giá thủ công ảnh hưởng đến snapping.
- Chưa chia cạnh, xuất CSR hoặc tích hợp runtime; thời gian cạnh lớn nhất còn 140,494 giây.
- Cảnh báo Shapely/TestClient còn tồn tại.

## Next Steps

- Rà soát GeoJSON bị loại, xác định cặp cạnh ngược cùng đoạn đường và chia cạnh dài.
