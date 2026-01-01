import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
from datetime import datetime

# ================= Config =================
# ตั้งค่าหน้าเว็บ
st.set_page_config(page_title="แจ้งโอนเงิน - มิดี้ VIP", page_icon="🎵")

# URL ของ Google Sheet (เอาเฉพาะ ID หรือ URL เต็มก็ได้ แต่ระบบนี้ใช้ชื่อ Sheet)
SHEET_ID = st.secrets["sheet_id"] 

# ================= ฟังก์ชันเชื่อมต่อ Google Sheets =================
def get_google_sheet_client():
    # ดึงค่า Key จาก Secrets ของ Streamlit Cloud (ปลอดภัยกว่าใส่ในโค้ด)
    creds_dict = dict(st.secrets["gcp_service_account"])
    scope = ['https://spreadsheets.google.com/feeds','https://www.googleapis.com/auth/drive']
    creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
    client = gspread.authorize(creds)
    return client

# ================= ฟังก์ชันคำนวณสิทธิ์ (Logic เดิม) =================
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

# ================= หน้าเว็บ (UI) =================
st.title("🎵 ระบบแจ้งโอนเงิน - สังคมคนรักมิดี้ VIP")
st.info("กรุณาโอนเงินเข้าบัญชี: **ออมสิน 020300995519 (เดือนฉาย ท้าวเขื่อน)** เท่านั้น")

with st.form("slip_form"):
    uploaded_file = st.file_uploader("1. อัปโหลดรูปสลิป", type=['png', 'jpg', 'jpeg'])
    sender_name = st.text_input("2. ชื่อบัญชีสมาชิกของคุณ (ต้องตรงกับในระบบ)", placeholder="พิมพ์ชื่อให้ถูกต้อง...")
    amount = st.number_input("3. ยอดโอน (ต้องเต็มร้อย ห้ามมีเศษ)", min_value=100, step=100)
    trans_time = st.time_input("4. เวลาที่โอน (ระบุตามสลิป)")
    
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
                    
                    # 1. บันทึก Log
                    try:
                        log_ws = sheet.worksheet("Transaction_Logs")
                    except:
                        log_ws = sheet.add_worksheet(title="Transaction_Logs", rows=1000, cols=10)
                        log_ws.append_row(["Timestamp", "ผู้โอน", "ยอดเงิน", "เวลาโอน", "สถานะ"])
                    
                    months_got = int(amount / 100)
                    
                    # 2. ค้นหาและอัปเดตสมาชิก
                    member_ws = sheet.worksheet("Sheet1") # แก้ชื่อ Sheet รายชื่อสมาชิกให้ตรง
                    try:
                        # ค้นหาชื่อใน Column G (Col 7)
                        cell = member_ws.find(sender_name, in_column=7)
                        
                        if cell:
                            # ดึงสิทธิ์เดิม (Col E = 5)
                            current_perm = member_ws.cell(cell.row, 5).value
                            new_perm = calculate_next_permission(current_perm, amount)
                            
                            # อัปเดตสิทธิ์ใหม่
                            member_ws.update_cell(cell.row, 5, new_perm)
                            
                            # บันทึก Log ว่าสำเร็จ
                            log_ws.append_row([str(datetime.now()), sender_name, amount, str(trans_time), f"Success: +{months_got} months"])
                            
                            st.success(f"🎉 เรียบร้อย! คุณ {sender_name} ได้รับสิทธิ์เพิ่ม {months_got} เดือน")
                            st.write(f"**สิทธิ์ใหม่ของคุณคือ:** `{new_perm}`")
                            st.balloons()
                        else:
                            # ไม่เจอชื่อ
                            log_ws.append_row([str(datetime.now()), sender_name, amount, str(trans_time), "Error: Name Not Found"])
                            st.warning(f"⚠️ บันทึกข้อมูลแล้ว แต่ไม่พบชื่อ '{sender_name}' ในระบบ (สิทธิ์ยังไม่อัปเดต) กรุณาติดต่อแอดมิน")
                            
                    except Exception as e:
                        st.error(f"เกิดข้อผิดพลาดในการค้นหา: {e}")

            except Exception as e:
                st.error(f"ระบบขัดข้อง: {e}")