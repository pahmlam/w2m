# Nhận diện cặp cạnh ngược cùng đoạn đường

**Date:** 2026-11-07 16:25  
**Status:** Completed

## Summary

Đã bổ sung nhận diện cạnh ngược trên graph SCC để bước chia cạnh sau có thể dùng
chung vị trí chia cho hai chiều. Mapping được ràng buộc với graph nguồn bằng checksum.

## Changes Made

- Ghép theo endpoint đảo, osmid, cờ hai chiều, thông tin tầng/cầu/hầm và geometry.
- Giữ trọng số từng chiều; xuất danh sách không ghép, lý do và ứng viên mơ hồ.
- CLI xuất JSON/metadata qua staging, kiểm tra nạp lại, không sửa graph nguồn.
- Thêm 30 test về cạnh song song, hình học, one-way, tốc độ khác nhau và lỗi artifact.

## Files Affected

- `backend/app/services/graph_reverse_edges.py` — logic ghép tất định.
- `backend/scripts/prepare_reverse_edges.py` — CLI và provenance.
- `backend/tests/test_graph_reverse_edges.py` — regression test.
- `backend/data/README.md`, `docs/plans/W2M-MVP-Plan.md` — hợp đồng mapping và tiến độ.

## Technical Decisions

- Chỉ ghép khi duy nhất ở cả hai phía; không dùng edge key để giải quyết mơ hồ.
- Dùng sai số geometry 0,01 m đã có ở bước chuẩn hóa; không tự sửa hình học.
- Mapping là artifact đi kèm; graph và trọng số hai chiều giữ nguyên.

## Verification

- **Tests:** 223 test backend đạt, không bỏ qua; 45 cảnh báo deprecation.
- **Build/Lint/Typecheck:** Ruff đạt; không chạy frontend build/typecheck vì không đổi frontend.
- **Manual Verification:** CLI trên SCC Hà Nội tạo
  `backend/data/reverse-edges/drive-20261106T092834Z-car-v1-reverse-v1/`:
  13.803 cặp/27.606 cạnh ghép, 7.860 cạnh one-way không ghép, không ca mơ hồ.
  Kiểm tra độc lập phủ đủ 35.466 cạnh đúng một lần, tiêu chí mọi cặp và checksum.

## Known Issues / Limitations

- Self-loop, metadata thiếu hoặc chuỗi geometry khác cách lấy mẫu không tự ghép.
- Dữ liệu khác có ca mơ hồ cần rà soát; chưa chia cạnh hoặc tích hợp runtime.

## Next Steps

- Chia cạnh trên 60 giây, dùng vị trí chia tương ứng cho các cặp đã xác nhận.
