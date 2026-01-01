import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
from datetime import datetime, time
import easyocr
import numpy as np
import cv2
import re

# ================= Config =================
st.set_page_config(page_title="แจ้งโอนเงิน - มิดี้ VIP", page_icon="🎵")

# URL ของ Google Sheet
SHEET_ID = st.secrets["sheet_id"] 

# ================= โหลด AI อ่านภาพ (Cache ไว้จะได้ไม่โหลดใหม่ทุกครั้ง) =================
@st.cache_resource
def load_ocr_reader():
    return easyocr.Reader(['en'], gpu=False) # อ่านตัวเลขใช้แค่ en ก็พอ เร็วกว่า

# ฟังก์ชันดึงเวลาจากภาพ
def extract_time_from_image(image_bytes):
    try:
        reader = load_ocr_reader()
        # แปลงภาพ
        file_bytes = np.asarray(bytearray(image_bytes.read()), dtype=np.uint8)
        image = cv2.imdecode(file_bytes, 1)
        
        # อ่านข้อความ
        result = reader.readtext(image, detail=0)
        full_text = " ".join(result)
        
        # ค้นหาแพทเทิร์นเวลา (เช่น 12:30, 12.30)
        # Regex: หาตัวเลข 1-2 หลัก ตามด้วย : หรือ . และตามด้วยตัวเลข 2 หลัก
        match = re.search(r'(\d{1,2})[:.](\d{2})', full_text)
        
        if match:
            h, m = match.groups()
            h, m = int(h), int(m)
            if 0 <= h < 24 and 0 <= m < 60:
                return time(h, m)
    except Exception as e:
        pass # ถ้าอ่านไม่ได้ ให้คืนค่า None
    return None

# ================= เชื่อมต่อ Google Sheets =================
def get_google_sheet_client():
    creds_dict = dict(st.secrets["gcp_service_account"])
    scope = ['https://spreadsheets.google.com/feeds','https://www.googleapis.com/auth/drive']
    creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
    client = gspread.authorize(creds)
    return client

# ================= คำนวณสิทธิ์ =================
def calculate_next_permission(current_perm, amount):
    months_to_add = int(amount / 100)
    if months_to_add == 0: return current_perm
    covered_months = set()
    
    if current_perm and str(current_perm).strip() not in ["-", "", "nan", "None"]:
        parts = str(current_perm).split(',')
        for part in parts:
            try:
                p = part.strip().split(':')
                if len(p) < 2: continue
                year = int(p[0])
                range_str = p[1]
                if '-' in range_str:
                    s, e = map(int, range_str.split('-'))
                    for m in range(s, e + 1): covered_months.add((year, m))
                else:
                    covered_months.add((year, int(range_str)))
            except: continue

    if not covered_months:
        now = datetime.now()
        start_y = now.year + 543
        start_m = now.month
        current_y, current_m = start_y, start_m - 1
        if current_m == 0: current_m = 12; current_y -= 1
    else:
        current_y, current_m = max(covered_months)

    for _ in range(months_to_add):
        current_m += 1
        if current_m > 12: current_m = 1; current_y += 1
        covered_months.add((current_y, current_m))

    sorted_months = sorted(list(covered_months))
    if not sorted_months: return ""

    data_by_year = {}
    for y, m in sorted_months:
        if y not in data_by_year: data_by_year[y] = []
        data_by_year[y].append(m)

    final_parts = []
    for y in sorted(data_by_year.keys()):
        months = sorted(data_by_year[y])
        ranges = []
        range_start = months[0]
        prev = months[0]
        for m in months[1:]:
            if m != prev + 1:
                ranges.append(str(range_start) if range_start == prev else f"{range_start}-{prev}")
                range_start = m
            prev = m
        ranges.append(str(range_start) if range_start == prev else f"{range_start}-{prev}")
        
        for r in ranges: final_parts.append(f"{y}:{r}:*")

    return " , ".join(final_parts)

# ================= UI หน้าเว็บ =================
st.title("🎵 ระบบแจ้งโอนเงิน - สังคมคนรักมิดี้ VIP")
st.info("กรุณาโอนเงินเข้าบัญชี: **ออมสิน 020300995519** เท่านั้น")

with st.form("slip_form"):
    uploaded_file = st.file_uploader("1. อัปโหลดรูปสลิป", type=['png', 'jpg', 'jpeg'])
    
    # ตัวแปรเก็บค่าเวลาเริ่มต้น
    default_time = datetime.now().time()
    
    # --- ส่วน Logic อ่านเวลาอัตโนมัติ ---
    if uploaded_file is not None:
        with st.spinner("กำลังอ่านเวลาจากสลิป..."):
            # ต้อง reset pointer ของไฟล์เพื่อให้ OCR อ่านได้ แล้วค่อยให้ uploader อ่านต่อ
            extracted_time = extract_time_from_image(uploaded_file)
            uploaded_file.seek(0) # reset file pointer
            
            if extracted_time:
                default_time = extracted_time
                st.success(f"🤖 อ่านเวลาเจอแล้ว: {default_time.strftime('%H:%M')} (ตรวจสอบอีกครั้ง)")
            else:
                st.warning("🤖 อ่านเวลาไม่เจอ กรุณาระบุเอง")
    
    sender_name = st.text_input("2. ชื่อบัญชีสมาชิกของคุณ (ต้องตรงกับในระบบ)", placeholder="พิมพ์ชื่อให้ถูกต้อง...")
    amount = st.number_input("3. ยอดโอน (ต้องเต็มร้อย ห้ามมีเศษ)", min_value=100, step=100)
    
    # ช่องเวลาจะเปลี่ยน auto ถ้า AI อ่านเจอ
    trans_time_str = st.text_input("4. เวลาที่โอน (เช่น 14.30)", value=default_time.strftime('%H:%M'))
    
    submitted = st.form_submit_button("✅ ยืนยันการแจ้งโอน")

    if submitted:
        if not uploaded_file:
            st.error("❌ กรุณาอัปโหลดสลิป")
        elif not sender_name:
            st.error("❌ กรุณาระบุชื่อผู้โอน")
        elif amount % 100 != 0:
            st.error("❌ ยอดเงินต้องเป็นจำนวนเต็มร้อย (เช่น 100, 200) เท่านั้น")
        else:
            try:
                with st.spinner("กำลังเชื่อมต่อฐานข้อมูล..."):
                    client = get_google_sheet_client()
                    sheet = client.open_by_key(SHEET_ID)
                    
                    try:
                        log_ws = sheet.worksheet("Transaction_Logs")
                    except:
                        log_ws = sheet.add_worksheet(title="Transaction_Logs", rows=1000, cols=10)
                        log_ws.append_row(["Timestamp", "ผู้โอน", "ยอดเงิน", "เวลาโอน", "สถานะ"])
                    
                    months_got = int(amount / 100)
                    member_ws = sheet.worksheet("Members")
                    
                    try:
                        cell = member_ws.find(sender_name, in_column=7)
                        if cell:
                            current_perm = member_ws.cell(cell.row, 5).value
                            new_perm = calculate_next_permission(current_perm, amount)
                            member_ws.update_cell(cell.row, 5, new_perm)
                            
                            log_ws.append_row([str(datetime.now()), sender_name, amount, str(trans_time), f"Success: +{months_got} months"])
                            
                            st.success(f"🎉 เรียบร้อย! คุณ {sender_name} ได้รับสิทธิ์เพิ่ม {months_got} เดือน")
                            st.write(f"**สิทธิ์ใหม่ของคุณคือ:** `{new_perm}`")
                            st.balloons()
                        else:
                            log_ws.append_row([str(datetime.now()), sender_name, amount, str(trans_time), "Error: Name Not Found"])
                            st.warning(f"⚠️ บันทึกข้อมูลแล้ว แต่ไม่พบชื่อ '{sender_name}' ในระบบ (สิทธิ์ยังไม่อัปเดต) กรุณาติดต่อแอดมิน")
                    except Exception as e:
                        st.error(f"เกิดข้อผิดพลาดในการค้นหา: {e}")
            except Exception as e:
                st.error(f"ระบบขัดข้อง: {e}")



