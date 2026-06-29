# -*- coding: utf-8 -*-
import re

def read_single_digit(d):
    digits = {
        "0": "không", "1": "một", "2": "hai", "3": "ba", "4": "bốn",
        "5": "năm", "6": "sáu", "7": "bảy", "8": "tám", "9": "chín"
    }
    return digits.get(d, "")

def read_three_digits(n, show_hundred=True):
    if n == 0:
        return ""
    hundred = n // 100
    remain = n % 100
    ten = remain // 10
    one = remain % 10
    
    words = []
    if hundred > 0 or show_hundred:
        words.append(read_single_digit(str(hundred)) + " trăm")
        
    if ten > 0:
        if ten == 1:
            words.append("mười")
        else:
            words.append(read_single_digit(str(ten)) + " mươi")
            
        if one > 0:
            if one == 1 and ten > 1:
                words.append("mốt")
            elif one == 5:
                words.append("lăm")
            else:
                words.append(read_single_digit(str(one)))
    else:
        if remain > 0:
            if hundred > 0 or show_hundred:
                words.append("lẻ")
            words.append(read_single_digit(str(one)))
            
    return " ".join(words)

def num_to_vietnamese_words(num_str):
    if not num_str:
        return ""
    
    # Số thập phân
    if "." in num_str:
        parts = num_str.split(".")
        if len(parts) == 2:
            left = num_to_vietnamese_words(parts[0])
            right = " ".join([read_single_digit(d) for d in parts[1]])
            return f"{left} phẩy {right}"
            
    try:
        num = int(num_str)
    except ValueError:
        return num_str
        
    if num == 0:
        return "không"
        
    units = ["", "nghìn", "triệu", "tỷ"]
    words = []
    
    temp = num
    i = 0
    while temp > 0:
        chunk = temp % 1000
        if chunk > 0 or i == 0:
            chunk_words = read_three_digits(chunk, show_hundred=(temp >= 1000 or chunk >= 100))
            if chunk_words:
                unit = units[i]
                if unit:
                    words.insert(0, f"{chunk_words} {unit}")
                else:
                    words.insert(0, chunk_words)
        temp = temp // 1000
        i += 1
        if i >= len(units):
            units.append("tỷ")
            
    return " ".join(words).strip()

ABBREVIATIONS = {
    r"\bTP\b": "thành phố",
    r"\bHN\b": "Hà Nội",
    r"\bHCM\b": "Hồ Chí Minh",
    r"\bđ\b": "đồng",
    r"\bkm\b": "ki-lô-mét",
    r"\bkg\b": "ki-lô-gam",
    r"\bm\b": "mét",
    r"\bcm\b": "xen-ti-mét",
    r"\bmm\b": "mi-li-mét",
    r"\bg\b": "gam",
    r"\btnhh\b": "trách nhiệm hữu hạn",
    r"\bcp\b": "cổ phần",
    r"\bđ/phút\b": "đồng trên phút",
}

SYMBOLS = {
    "&": " và ",
    "%": " phần trăm ",
    "+": " cộng ",
    "-": " trừ ",
    "$": " đô la ",
    "@": " a còng ",
}

def normalize_vietnamese_text(text):
    if not text:
        return ""
    
    # 1. Thay chữ viết tắt
    for pattern, repl in ABBREVIATIONS.items():
        text = re.sub(pattern, repl, text, flags=re.IGNORECASE)
        
    # 2. Thay ký hiệu đặc biệt
    for sym, repl in SYMBOLS.items():
        text = text.replace(sym, repl)
        
    # 3. Thay thế số (thập phân và nguyên)
    def replace_num(match):
        return num_to_vietnamese_words(match.group(0))
        
    text = re.sub(r"\d+\.\d+|\d+", replace_num, text)
    
    # 4. Làm sạch khoảng trắng thừa
    text = re.sub(r"\s+", " ", text).strip()
    return text
