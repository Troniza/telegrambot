import sqlite3
from flask import Flask, request, jsonify, render_template
import requests

app = Flask(__name__)

# تنظیمات اولیه
verify_url = "https://panel.aqayepardakht.ir/api/v2/verify"
pin_code = "sandbox"  # پین کد تست


def get_amount_from_db(invoice_id):
    
    conn = sqlite3.connect("invoices.db")
    cursor = conn.cursor()

    query = "SELECT amount, transid FROM transactions WHERE invoice_id = ?"
    cursor.execute(query, (invoice_id,))
    result = cursor.fetchone()
    conn.close()

    return result if result else None

@app.route('/callback', methods=['POST'])
def callback():
    
    print("Headers:", request.headers)
    print("Body:", request.data)

    # پردازش داده‌ها
    if request.is_json:
        data = request.json
    elif request.form:
        data = request.form.to_dict()
    else:
        return jsonify({"error": "Unsupported Media Type"}), 415

    print("Received Data:", data)

    # بررسی پارامترها
    invoice_id = data.get('invoice_id')
    transid = data.get('transid')
    status = data.get('status')  # دریافت status از کالبک

    if not invoice_id or not transid or status is None:
        return jsonify({"error": "پارامترهای لازم ارسال نشده است"}), 400

    # اگر status برابر با ۱ نباشه
    if status != '1':
        if status == '2':  # اگر status برابر با ۲ باشد
            message = "تراکنش قبلاً تایید شده و پرداخت شده است."
        else:
            message = "تراکنش انجام نشد."
        return render_template('status.html', message=message)

    # استخراج مبلغ از دیتابیس
    result = get_amount_from_db(invoice_id)
    if not result:
        return jsonify({"error": "Invoice ID not found in database"}), 404

    amount = result[0]
    print(f"Retrieved amount from DB: {amount}")

    # داده‌های مورد نیاز برای وریفای
    verify_data = {
        "pin": pin_code,
        "amount": amount,
        "transid": transid
    }
    print("Sending data to verify API:", verify_data)

    # ارسال درخواست وریفای
    try:
        response = requests.post(verify_url, json=verify_data)
        print("Response Status Code:", response.status_code)

        if response.status_code == 200:
            result = response.json()
            print("Response JSON:", result)

            
            try:
                code = int(result.get("code", -99))  # مقدار پیش‌فرض برای وضعیت نامشخص
            except ValueError:
                code = -99  

            # وضعیت‌ها
            if code == 1:
                message = "پرداخت شما با موفقیت انجام شد."
            elif code == 0:
                message = "پرداخت انجام نشد، لطفاً دوباره تلاش کنید."
            elif code == 2:
                message = "این تراکنش قبلاً وریفای و تایید شده است."
            else:
                message = f"وضعیت نامشخص دریافت شد: {code}"

        else:
            message = f"خطای غیرمنتظره از سمت سرور: {response.status_code}"

    except Exception as e:
        message = f"خطا در ارتباط با API: {str(e)}"

    # نمایش نتیجه در هتمل
    return render_template('status.html', message=message)

if __name__ == '__main__':
    app.run(debug=True, port=5000)