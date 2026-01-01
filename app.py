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

# --- ID ชีตของคุณ (คงเดิม) ---
SHEET_ID = '1hQRW8mJVD6yMp5v2Iv1i3hCLTR3fosWyKyTk_Ibj3YQ'
MEMBER_TAB_NAME = 'Members'
LOG_TAB_NAME = 'Transaction_Logs'

# ================= โหลด AI และเชื่อมต่อ =================
@st.cache_resource
def load_ocr_reader():
    return easyocr.Reader(['en'], gpu=False)

def get_google_sheet_client():
    try:
        creds_dict = dict(st.secrets["gcp_service_account"])
        scope = ['https://spreadsheets.google.com/feeds','https://www.googleapis.com/auth/drive']
        creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
        client = gspread.authorize(creds)
        return client
    except Exception as e:
        st.error(f"❌ Error ตั้งค่ากุญแจ: {e}")
        return None

# ================= ฟังก์ชันช่วย =================
def extract_time_from_image(image_bytes):
    try:
        reader = load_ocr_reader()
        file_bytes = np.asarray(bytearray(image_bytes.read()), dtype=np.uint8)
        image = cv2.imdecode(file_bytes, 1)
        result = reader.readtext(image, detail=0)
        full_text = " ".join(result)
        match = re.search(r'(\d{1,2})[:.](\d{2})', full_text)
        if match:
            h, m = map(int, match.groups())
            if 0 <= h < 24 and 0 <= m < 60: return time(h, m)
    except: pass
    return None

def calculate_next_permission(current_perm, amount):
    months_to_add = int(amount / 100)
    if months_to_add == 0: return current_perm
    covered_months = set()
    
    # แกะสิทธิ์เดิม
    if str(current_perm).strip() not in ["-", "", "nan", "None"]:
        for part in str(current_perm).split(','):
            try:
                p = part.strip().split(':')
                if len(p) >= 2:
                    y = int(p[0])
                    r = p[1]
                    if '-' in r:
                        s, e = map(int, r.split('-'))
                        for m in range(s, e+1): covered_months.add((y, m))
                    else:
                        covered_months.add((y, int(r)))
            except: continue

    # หาเดือนล่าสุด
    if not covered_months:
        now = datetime.now()
        cur_y, cur_m = now.year + 543, now.month - 1
        if cur_m == 0: cur_m = 12; cur_y -= 1
    else:
        cur_y, cur_m = max(covered_months)

    # บวกเดือนเพิ่ม
    for _ in range(months_to_add):
        cur_m += 1
        if cur_m > 12: cur_m = 1; cur_y += 1
        covered_months.add((cur_y, cur_m))

    # จัดรูปแบบกลับ
    data_by_year = {}
    for y, m in sorted(list(covered_months)):
        if y not in data_by_year: data_by_year[y] = []
        data_by_year[y].append(m)

    final_parts = []
    for y in sorted(data_by_year.keys()):
        ms = sorted(data_by_year[y])
        ranges = []
        start = prev = ms[0]
        for m in ms[1:]:
            if m != prev + 1:
                ranges.append(str(start) if start == prev else f"{start}-{prev}")
                start = m
            prev = m
        ranges.append(str(start) if start == prev else f"{start}-{prev}")
        for r in ranges: final_parts.append(f"{y}:{r}:*")

    return " , ".join(final_parts)

# ================= UI หน้าเว็บ =================
st.title("🎵 ระบบแจ้งโอนเงิน - มิดี้ VIP")
st.info("กรุณาโอนเงินเข้าบัญชี: **ออมสิน 020300995519** เท่านั้น")

with st.form("slip_form"):
    uploaded_file = st.file_uploader("1. อัปโหลดรูปสลิป", type=['png', 'jpg', 'jpeg'])
    
    default_time = datetime.now().time()
    if uploaded_file:
        with st.spinner("⏳ กำลังอ่านเวลา..."):
            t = extract_time_from_image(uploaded_file)
            uploaded_file.seek(0)
            if t:
                default_time = t
                st.success(f"🤖 อ่านเวลาได้: {t.strftime('%H:%M')}")
    
    sender_name = st.text_input("2. ชื่อบัญชีสมาชิก หรือ รหัสสมาชิก", placeholder="เช่น ป๋า หรือ MBR-123")
    amount = st.number_input("3. ยอดโอน (เต็มร้อย)", min_value=100, step=100)
    trans_time = st.time_input("4. เวลาโอน", value=default_time, step=60)
    
    if st.form_submit_button("✅ ยืนยันการแจ้งโอน"):
        if not uploaded_file: st.error("❌ ลืมแนบสลิป")
        elif not sender_name: st.error("❌ ลืมใส่ชื่อ")
        elif amount % 100 != 0: st.error("❌ ยอดเงินต้องเต็มร้อย")
        else:
            try:
                client = get_google_sheet_client()
                if client:
                    sheet = client.open_by_key(SHEET_ID)
                    
                    # 1. เขียน Log
                    try:
                        log_ws = sheet.worksheet(LOG_TAB_NAME)
                        log_ws.append_row([str(datetime.now()), sender_name, amount, str(trans_time), "Processing..."])
                    except: pass # ข้ามถ้า log มีปัญหา

                    # ==========================================
                    # 2. ค้นหาสมาชิก (Logic ใหม่ที่อัปเกรดแล้ว)
                    # ==========================================
                    member_ws = sheet.worksheet(MEMBER_TAB_NAME)
                    
                    # ดึงข้อมูลทั้งหมดมาเช็คทีละแถว (เพื่อรองรับ , และ Col A)
                    all_values = member_ws.get_all_values()
                    
                    found_row_index = None
                    current_perm_val = ""
                    search_key = sender_name.strip()
                    
                    # เริ่มวนลูปหา (เริ่ม i=1 เพื่อข้ามหัวตาราง)
                    for i, row in enumerate(all_values):
                        if i == 0: continue 
                        
                        # Col A (index 0) = MemberID
                        # Col G (index 6) = ชื่อสมาชิก (อาจมีคอมม่า)
                        col_a_id = str(row[0]).strip() if len(row) > 0 else ""
                        col_g_name = str(row[6]).strip() if len(row) > 6 else ""
                        
                        # แยกชื่อใน Col G ด้วยคอมม่า (เช่น "MBR-123,ป๋า" -> ["MBR-123", "ป๋า"])
                        valid_names = [n.strip() for n in col_g_name.split(',')]
                        
                        # เช็คว่าสิ่งที่ user พิมพ์ ตรงกับ Col A หรือ ชื่อใดชื่อหนึ่งใน Col G ไหม?
                        if search_key == col_a_id or search_key in valid_names:
                            found_row_index = i + 1 # +1 เพราะใน sheet เริ่มนับที่ 1
                            current_perm_val = str(row[4]) if len(row) > 4 else "" # Col E = index 4
                            break
                    
                    # 3. ผลลัพธ์
                    if found_row_index:
                        new_perm = calculate_next_permission(current_perm_val, amount)
                        
                        # อัปเดต Column E (5)
                        member_ws.update_cell(found_row_index, 5, new_perm)
                        
                        st.balloons()
                        st.success(f"🎉 เรียบร้อย! อัปเดตสิทธิ์ให้คุณ '{sender_name}' แล้ว")
                        st.code(f"สิทธิ์ใหม่: {new_perm}")
                    else:
                        st.warning(f"⚠️ ไม่พบข้อมูล '{sender_name}' ในระบบ")
                        st.write("ลองตรวจสอบตัวสะกด หรือใช้รหัสสมาชิก (Member ID) แทน")

            except Exception as e:
                st.error(f"❌ ระบบขัดข้อง: {e}")
