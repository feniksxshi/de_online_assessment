Một trợ lý AI được hỏi: "Thiết kế pipeline trên AWS thu log hằng ngày từ hệ thống của khách vào data lake, và tổ chức knowledge base cho RAG." Nó trả lời như sau: 
> Bạn nên lưu toàn bộ log vào **S3 Standard-IA vì đây là lựa chọn mặc định rẻ nhất cho data lake**. Để thu dữ liệu, cấu hình một **Glue job đọc trực tiếp từ database RDS production của khách mỗi 5 phút — đây là pattern** chuẩn cho near-real-time. Dữ liệu nên chuyển sang **Parquet, một format lưu theo hàng (row-based) nên ghi rất nhanh**, phù hợp cho analytics. Với các bước transform nặng chạy khoảng **30–45 phút, dùng AWS Lambda là phù hợp nhất** vì không phải quản lý server. Về knowledge base cho RAG, hãy **chia tài liệu thành các chunk cố định 4.000 token — kích thước này luôn tốt nhất** cho mọi loại tài liệu. Cuối cùng, **không cần đánh version cho knowledge base, vì bản mới nhất luôn là bản đúng** — cứ ghi đè là được. 

---
## "S3 Standard-IA là lựa chọn mặc định rẻ nhất cho data lake" - SAI
- **Vì sao sai**: 
	- Log hệ thống đổ về hằng ngày, tức phải ghi dữ liệu mới liên tục và có thể cần đọc ngay để thực hiện transform. 
	- S3 Standard-IA charge trên mỗi GB dữ liệu truy xuất (Retrieval Fee) và charge nếu xóa/thay đổi dữ liệu trước 30 ngày [1]. Ingest log trực tiếp vào Standard-IA sẽ làm chi phí đội lên rất cao do tần suất ghi/đọc dữ liệu mới lớn.
- **Hướng sửa đổi**: Raw layer trong data lake (nơi lưu raw logs) dùng **S3 Standard**. Sau đó, cấu hình **S3 Lifecycle Policy** để tự động chuyển log cũ (ví dụ: sau 30 hoặc 90 ngày) sang S3 Standard-IA hoặc S3 Glacier để tối ưu chi phí.
- **Nguồn kiểm chứng**: [1] https://aws.amazon.com/s3/pricing/ 

## "Cấu hình một Glue job đọc trực tiếp từ database RDS production của khách mỗi 5 phút" - SAI
- **Vì sao sai**:
	- **Về tính năng**: AWS Glue là công cụ ETL dạng batch, mất từ 1–3 phút chỉ để khởi tạo cluster (cold start). Chạy Glue job mỗi 5 phút là bất khả thi và cực kỳ lãng phí tài nguyên tính toán (DPU).
	- **Về an toàn hệ thống**: Scan trực tiếp vào Database Production mỗi 5 phút sẽ làm cạn kiệt tài nguyên (CPU/RAM/IOPS), dễ gây sập hệ thống đang phục vụ khách hàng.
- **Hướng sửa đổi**: 
	- Để đạt near-real-time mà không ảnh hưởng Production, dùng **CDC (Change Data Capture)** bằng cách cấu hình **AWS DMS (Database Migration Service)/Debezium** để đọc liên tục từ **binlog/wal-log của RDS** và đẩy về S3. 
	- Nếu thu thập logs theo ngày, chỉ cần chạy Glue job 1 lần/ngày vào khung giờ thấp điểm (off-peak hours).	
- **Nguồn kiểm chứng**:
	- https://docs.aws.amazon.com/prescriptive-guidance/latest/serverless-etl-aws-glue/best-practices.html
	- https://docs.aws.amazon.com/prescriptive-guidance/latest/migration-database-rehost-tools/dms.html 
	- https://docs.aws.amazon.com/msk/latest/developerguide/mkc-debeziumsource-connector-example.html

## "Parquet, một format lưu theo hàng (row-based) nên ghi rất nhanh" - SAI
- **Vì sao sai**: 
	- Parquet là định dạng lưu trữ theo cột (column-based / columnar), không phải theo hàng. 
	- Vì lưu theo cột, nó compress data rất tốt và tối ưu cho việc truy vấn analytic (chỉ quét các cột cần thiết), nhưng tốc độ ghi chậm hơn các định dạng row-based (như Avro hoặc JSON) vì tốn tài nguyên sắp xếp dữ liệu thành các cột.
- **Hướng sửa đổi**: 
	- Đính chính lại kiến thức: Parquet giúp tối ưu hóa hiệu năng và chi phí truy vấn analytic (khi dùng với Athena/Glue). 
	- Raw log ban đầu nên ghi dưới dạng JSON/Avro, sau đó dùng Glue job chuyển đổi sang Parquet để lưu trữ lâu dài.
- **Nguồn kiểm chứng**: 
	- https://www.tigerdata.com/learn/columnar-databases-vs-row-oriented-databases-which-to-choose
	- https://parquet.apache.org/docs/ 

## "Với các bước transform nặng chạy khoảng 30–45 phút, dùng AWS Lambda là phù hợp nhất" - SAI 
- **Vì sao sai**: 
	- AWS Lambda là dịch vụ serverless bị giới hạn thời gian chạy tối đa (Hard timeout) là 15 phút [1]. 
	- Một task chạy 30–45 phút chắc chắn sẽ bị sập giữa chừng và không bao giờ hoàn thành được trên Lambda.
- **Hướng sửa đổi**: Với các tác vụ nặng (heavy transformation) chạy từ 30 phút trở lên, công cụ phù hợp nhất là **AWS Glue (Spark job)** hoặc **Amazon EMR** [2]. Chúng có khả năng xử lý phân tán và không bị giới hạn timeout 15 phút.
- **Nguồn kiểm chứng**: \
	[1] https://docs.aws.amazon.com/lambda/latest/dg/gettingstarted-limits.html	\
	[2] https://www.geeksforgeeks.org/devops/difference-between-emr-and-glue/ 

## "Chia tài liệu thành các chunk cố định 4.000 token — kích thước này luôn tốt nhất cho mọi loại tài liệu & Không cần đánh version cho knowledge base, vì bản mới nhất luôn là bản đúng" - SAI
- **Vì sao sai**:
	- **Về Chunk size**: 4.000 token là quá lớn cho RAG. Chunk lớn làm loãng thông tin, vượt quá ngữ cảnh (context window) của nhiều LLM đời cũ, và làm tăng chi phí token khi gọi API. Không có kích thước nào là "luôn tốt nhất cho mọi loại tài liệu".
	- **Về Versioning**:
		- Hệ thống RAG trong doanh nghiệp cần cập nhật liên tục. Nếu không đánh version, khi dữ liệu mới bị lỗi hoặc bị chèn ép thông tin sai (data poisoning), chúng ta sẽ không thể rollback (khôi phục) lại trạng thái chuẩn cũ.
		- Ngoài ra, việc ghi đè trực tiếp mà không kiểm soát dễ làm mất đồng bộ giữa Vector DB và Data Lake.
- **Hướng sửa đổi**:
	- Sử dụng chunk size linh hoạt (thường từ 256–512 tokens kết hợp với chunk overlap 10–20%) tùy thuộc vào cấu trúc tài liệu.
	- Bật S3 Versioning cho bucket chứa Knowledge Base. Khi cập nhật tài liệu, cần chạy pipeline để xóa các vector cũ tương ứng trong Vector DB trước khi upsert vector mới.
- **Nguồn kiểm chứng**: https://docs.aws.amazon.com/prescriptive-guidance/latest/writing-best-practices-rag/best-practices.html