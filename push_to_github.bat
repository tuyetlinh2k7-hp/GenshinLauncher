@echo off
chcp 65001 > nul
title Đẩy mã nguồn Genshin Launcher lên GitHub

echo ======================================================================
echo       🌸 HỖ TRỢ ĐẨY MÃ NGUỒN GENSHIN LAUNCHER LÊN GITHUB 🌸
echo ======================================================================
echo.
echo Bước 1: Hãy truy cập: https://github.com/new
echo         - Đặt tên Repository là: GenshinLauncher (hoặc Genshin-Impact-Launcher)
echo         - Chọn chế độ: Public hoặc Private tùy bạn
echo         - KHÔNG tích chọn "Add a README file" (vì thư mục đã có sẵn)
echo         - Bấm "Create repository"
echo.
echo Bước 2: Dán đường dẫn URL Repository của bạn vào bên dưới:
echo         (Ví dụ: https://github.com/tuyetlinh2k7-hp/GenshinLauncher.git)
echo.
set /p REPO_URL="Nhập Link GitHub Repository: "

if "%REPO_URL%"=="" (
    echo.
    echo [!] Bạn chưa nhập URL. Quá trình đã dừng.
    goto end
)

echo.
echo [*] Đang thiết lập nhánh main và đẩy mã nguồn lên GitHub...
git branch -M main
git remote remove origin 2>nul
git remote add origin %REPO_URL%
git push -u origin main

if %ERRORLEVEL% EQU 0 (
    echo.
    echo ======================================================================
    echo  ✅ THÀNH CÔNG! Mã nguồn đã được đẩy lên GitHub!
    echo     Xem ngay tại: %REPO_URL%
    echo ======================================================================
) else (
    echo.
    echo ======================================================================
    echo  ❌ Có lỗi xảy ra khi đẩy lên GitHub.
    echo     Vui lòng kiểm tra quyền đăng nhập GitHub hoặc URL đã nhập đúng chưa.
    echo ======================================================================
)

:end
echo.
pause
