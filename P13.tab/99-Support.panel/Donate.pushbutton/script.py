# -*- coding: utf-8 -*-
from pyrevit import script
import os

# 1. ตั้งค่าพื้นฐาน
output = script.get_output()

# 2. หา Path ของโฟลเดอร์ที่ Script นี้รันอยู่
cur_dir = os.path.dirname(os.path.abspath(__file__))
qr_paypal_path = os.path.join(cur_dir, 'qr_paypal.png')
qr_promptpay_path = os.path.join(cur_dir, 'qr_promptpay.png')

# 3. กำหนดขนาดหน้าต่าง Output
output.set_width(600)
output.set_height(450)

output.print_md("# 🙏 Support p13.extension")
output.print_md("---")

# 4. แสดงภาพขนานกันโดยใช้ HTML Table
# วิธีนี้จะบังคับให้ภาพทั้งสองเรียงกันในแนวนอน
html_layout = """
<table style="width:100%; border:none;">
  <tr>
    <td style="text-align:center; border:none;">
        <p><b>PayPal</b></p>
        <img src="{paypal}" width="250">
    </td>
    <td style="text-align:center; border:none;">
        <p><b>PromptPay</b></p>
        <img src="{promptpay}" width="250">
    </td>
  </tr>
</table>
""".format(paypal=qr_paypal_path, promptpay=qr_promptpay_path)

output.print_html(html_layout)

output.print_md("---")
output.print_md("ขอบคุณสำหรับการสนับสนุนครับ!")