# Tải snapshot mạng đường OSM offline

**Date:** 2026-11-06 16:15  
**Status:** Partially Completed

## Summary

Đã viết CLI tải mạng đường ô tô trong routing area và lưu snapshot để xây đồ thị offline.
Chưa chạy kiểm thử hoặc tải dữ liệu thật; người phát triển sẽ tự thực hiện các lệnh.

## Changes Made

- Tải mạng drive chưa simplify, giữ các thành phần rời rạc và cạnh song song có hướng.
- Chốt cùng thời điểm dữ liệu UTC cho mọi truy vấn Overpass trong một lần tải.
- Lưu GraphML, polygon truy vấn, cache phản hồi và manifest nguồn/thời điểm/checksum.
- Nạp lại GraphML kiểm tra kiểu graph, số node/cạnh trước khi công bố snapshot.
- Không ghi đè snapshot có sẵn; dọn staging khi lỗi và khôi phục cấu hình OSMnx.
- Thêm test giả lập OSMnx để routine CI không truy cập mạng.

## Files Affected

- `backend/scripts/download_osm.py` — CLI và lưu snapshot.
- `backend/tests/test_download_osm.py` — test topology, metadata, thời gian, lỗi và cleanup.
- `backend/app/config/settings.py`, `.env.example` — cấu hình thư mục snapshot.
- `README.md`, `backend/data/README.md` — lệnh dành cho người phát triển.
- `docs/plans/W2M-MVP-Plan.md` — phân biệt code đã viết với nghiệm thu chưa chạy.

## Technical Decisions

- Dùng optional extra data hiện có; chỉ import OSMnx khi tải, không cần cài thêm cho unit test.
- GraphML giữ trạng thái thô; projection, trọng số, SCC và chia cạnh thuộc bước sau.
- Dùng thư mục tạm cùng filesystem rồi rename để tránh công bố snapshot dở dang.
- Bản sao polygon và checksum gắn dữ liệu tải với đúng đầu vào.

## Verification

- **Tests:** đã viết, chưa chạy.
- **Build/Lint/Typecheck:** chưa chạy sau thay đổi.
- **Manual Verification:** rà soát code và API OSMnx chính thức; chưa xác minh snapshot thật.

## Known Issues / Limitations

Tải thật cần mạng và Overpass hỗ trợ lịch sử; timeout mặc định 180 giây.
Cache tạm bị dọn nếu lần tải thất bại. Snapshot chưa phải graph production;
readiness vẫn chưa được tích hợp.

## Next Steps

Người phát triển chạy Ruff, pytest và CLI với extra data; gửi manifest để kiểm tra trước khi nghiệm thu.
