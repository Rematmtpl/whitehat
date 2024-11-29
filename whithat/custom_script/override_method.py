import frappe   
from erpnext.accounts.doctype.subscription_plan.subscription_plan import get_prorate_factor
from frappe.utils import getdate
from dateutil import relativedelta
from frappe.utils import cint, flt, fmt_money, getdate, nowdate
from erpnext.accounts.doctype.pricing_rule.pricing_rule import get_pricing_rule_for_item


@frappe.whitelist()
def custom_get_plan_rate(
	plan, quantity=1, customer=None, start_date=None, end_date=None, prorate_factor=1
    ):
	plan = frappe.get_doc("Subscription Plan", plan)
	if plan.price_determination == "Fixed Rate":
		return plan.cost * prorate_factor

	elif plan.price_determination == "Based On Price List":
		
		if customer:
			customer_group = frappe.db.get_value("Customer", customer, "customer_group")
		else:
			customer_group = None
		price = custom_get_price(
			item_code=plan.item,
			price_list=plan.price_list,
			customer_group=customer_group,
			company=None,
			qty=quantity,
			customer = customer
		)
		
		if not price:
			return 0
		else:
			return price.price_list_rate * prorate_factor

	elif plan.price_determination == "Monthly Rate":
		start_date = getdate(start_date)
		end_date = getdate(end_date)

		no_of_months = relativedelta.relativedelta(end_date, start_date).months + 1
		cost = plan.cost * no_of_months

		# Adjust cost if start or end date is not month start or end
		prorate = frappe.db.get_single_value("Subscription Settings", "prorate")

		if prorate:
			cost -= plan.cost * get_prorate_factor(start_date, end_date)
		return cost
	
@frappe.whitelist()
def custom_get_price(item_code, price_list, customer_group, company, qty=1,customer=None):
	from erpnext.e_commerce.shopping_cart.cart import get_party

	template_item_code = frappe.db.get_value("Item", item_code, "variant_of")

	if price_list:
		price = frappe.get_all(
			"Item Price",
			fields=["price_list_rate", "currency"],
			filters={"price_list": price_list, "item_code": item_code,'customer':customer},
		)
		if template_item_code and not price:
			price = frappe.get_all(
				"Item Price",
				fields=["price_list_rate", "currency"],
				filters={"price_list": price_list, "item_code": template_item_code,'customer':customer},
			)
		
		if price:
			party = get_party()
			pricing_rule_dict = frappe._dict(
				{
					"item_code": item_code,
					"qty": qty,
					"stock_qty": qty,
					"transaction_type": "selling",
					"price_list": price_list,
					"customer_group": customer_group,
					"company": company,
					"conversion_rate": 1,
					"for_shopping_cart": True,
					"currency": frappe.db.get_value("Price List", price_list, "currency"),
					"doctype": "Sales Invoice",
				}
			)
			if party and party.doctype == "Customer":
				pricing_rule_dict.update({"customer": party.name})

			pricing_rule = get_pricing_rule_for_item(pricing_rule_dict)
			price_obj = price[0]

			if pricing_rule:
				# price without any rules applied
				mrp = price_obj.price_list_rate or 0

				if pricing_rule.pricing_rule_for == "Discount Percentage":
					price_obj.discount_percent = pricing_rule.discount_percentage
					price_obj.formatted_discount_percent = str(flt(pricing_rule.discount_percentage, 0)) + "%"
					price_obj.price_list_rate = flt(
						price_obj.price_list_rate * (1.0 - (flt(pricing_rule.discount_percentage) / 100.0))
					)

				if pricing_rule.pricing_rule_for == "Rate":
					rate_discount = flt(mrp) - flt(pricing_rule.price_list_rate)
					if rate_discount > 0:
						price_obj.formatted_discount_rate = fmt_money(rate_discount, currency=price_obj["currency"])
					price_obj.price_list_rate = pricing_rule.price_list_rate or 0

			if price_obj:
				price_obj["formatted_price"] = fmt_money(
					price_obj["price_list_rate"], currency=price_obj["currency"]
				)
				if mrp != price_obj["price_list_rate"]:
					price_obj["formatted_mrp"] = fmt_money(mrp, currency=price_obj["currency"])

				price_obj["currency_symbol"] = (
					not cint(frappe.db.get_default("hide_currency_symbol"))
					and (
						frappe.db.get_value("Currency", price_obj.currency, "symbol", cache=True)
						or price_obj.currency
					)
					or ""
				)

				uom_conversion_factor = frappe.db.sql(
					"""select	C.conversion_factor
					from `tabUOM Conversion Detail` C
					inner join `tabItem` I on C.parent = I.name and C.uom = I.sales_uom
					where I.name = %s""",
					item_code,
				)

				uom_conversion_factor = uom_conversion_factor[0][0] if uom_conversion_factor else 1
				price_obj["formatted_price_sales_uom"] = fmt_money(
					price_obj["price_list_rate"] * uom_conversion_factor, currency=price_obj["currency"]
				)

				if not price_obj["price_list_rate"]:
					price_obj["price_list_rate"] = 0

				if not price_obj["currency"]:
					price_obj["currency"] = ""

				if not price_obj["formatted_price"]:
					price_obj["formatted_price"], price_obj["formatted_mrp"] = "", ""

			return price_obj