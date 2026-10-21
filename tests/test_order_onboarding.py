import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.services.auth_service import create_session_token, SESSION_COOKIE_NAME


@pytest.mark.asyncio
async def test_order_lookup_endpoint():
    token = create_session_token("admin")
    cookies = {SESSION_COOKIE_NAME: token}
    
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", cookies=cookies) as client:
        # Test lookup endpoint with an order ID
        resp = await client.get("/api/orders/lookup?order_id=WF-10928")
        assert resp.status_code == 200
        data = resp.json()
        assert "found" in data
        assert "order" in data
        assert "order_id" in data["order"]


@pytest.mark.asyncio
async def test_customer_crud_with_order_details():
    token = create_session_token("admin")
    cookies = {SESSION_COOKIE_NAME: token}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", cookies=cookies) as client:
        # 1. Create customer with product, price, payment_method, delivery_time
        create_payload = {
            "name": "Vikram Singh",
            "phone": "9876543999",
            "order_id": "WF-99881",
            "product_name": "Premium Leather Jacket",
            "product_price": "₹3,499",
            "payment_method": "Cash on Delivery (COD)",
            "delivery_time": "Friday by 2 PM",
            "notes": "Flat 302, Green Park, Jaipur"
        }
        res_create = await client.post("/api/customers", json=create_payload)
        assert res_create.status_code == 200
        cust_id = res_create.json().get("customer_id")
        assert cust_id is not None

        # 2. Get customer details
        res_get = await client.get(f"/api/customers/{cust_id}")
        assert res_get.status_code == 200
        cust = res_get.json()
        assert cust["name"] == "Vikram Singh"
        assert cust["product_name"] == "Premium Leather Jacket"
        assert cust["product_price"] == "₹3,499"
        assert cust["payment_method"] == "Cash on Delivery (COD)"
        assert cust["delivery_time"] == "Friday by 2 PM"

        # 3. Update customer order details
        update_payload = {
            "name": "Vikram Singh",
            "phone": "9876543999",
            "order_id": "WF-99881",
            "product_name": "Premium Leather Jacket (XL)",
            "product_price": "₹3,799",
            "payment_method": "Prepaid (UPI)",
            "delivery_time": "Saturday by 11 AM",
            "notes": "Flat 302, Green Park, Jaipur"
        }
        res_put = await client.put(f"/api/customers/{cust_id}", json=update_payload)
        assert res_put.status_code == 200

        # Verify update
        res_get_updated = await client.get(f"/api/customers/{cust_id}")
        updated_cust = res_get_updated.json()
        assert updated_cust["product_name"] == "Premium Leather Jacket (XL)"
        assert updated_cust["product_price"] == "₹3,799"
        assert updated_cust["payment_method"] == "Prepaid (UPI)"
        assert updated_cust["delivery_time"] == "Saturday by 11 AM"

        # 4. Check CSV export includes new fields
        res_csv = await client.get("/api/customers/export-csv")
        assert res_csv.status_code == 200
        csv_text = res_csv.text
        assert "Product Name" in csv_text
        assert "Product Price" in csv_text
        assert "Delivery Time" in csv_text
        assert "Payment Method" in csv_text
        assert "Premium Leather Jacket (XL)" in csv_text

        # Cleanup test customer
        await client.delete(f"/api/customers/{cust_id}")
