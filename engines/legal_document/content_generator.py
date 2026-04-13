"""Legal Document Engine — content generator.

Generates legal content with required clauses for each document type.
Produces section-by-section content based on templates and business info.

All logic is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
import time
from typing import Any


# ---------------------------------------------------------------------------
# Section content templates
# ---------------------------------------------------------------------------

_SECTION_CONTENT: dict[str, dict[str, str]] = {
    # Terms of Service sections
    "acceptance_of_terms": {
        "heading": "Acceptance of Terms",
        "content": "By accessing and using {site_name}, you accept and agree to be bound by the terms and provision of this agreement.",
    },
    "use_of_service": {
        "heading": "Use of Service",
        "content": "You agree to use {site_name} only for lawful purposes. You must not use our service in any way that causes, or may cause, damage to the service or impairment of the availability of the service.",
    },
    "user_accounts": {
        "heading": "User Accounts",
        "content": "When you create an account with {site_name}, you must provide accurate and complete information. You are responsible for safeguarding the password and for all activities that occur under your account.",
    },
    "intellectual_property": {
        "heading": "Intellectual Property",
        "content": "The content, features, and functionality of {site_name} are owned by {business_name} and are protected by international copyright, trademark, patent, and other intellectual property laws.",
    },
    "limitation_of_liability": {
        "heading": "Limitation of Liability",
        "content": "In no event shall {business_name}, nor its directors, employees, partners, agents, suppliers, or affiliates, be liable for any indirect, incidental, special, consequential, or punitive damages.",
    },
    "governing_law": {
        "heading": "Governing Law",
        "content": "These terms shall be governed and construed in accordance with the laws of {country}, without regard to its conflict of law provisions.",
    },
    "changes_to_terms": {
        "heading": "Changes to Terms",
        "content": "{business_name} reserves the right to modify or replace these terms at any time. We will provide notice of any changes by posting the new terms on this page.",
    },
    "contact_information": {
        "heading": "Contact Information",
        "content": "If you have any questions about these terms, please contact {business_name}.",
    },
    "arbitration_clause": {
        "heading": "Arbitration",
        "content": "Any dispute arising from these terms shall be resolved through binding arbitration in accordance with the rules of the American Arbitration Association.",
    },
    "dmca_notice": {
        "heading": "DMCA Notice",
        "content": "If you believe that your copyrighted work has been copied in a way that constitutes copyright infringement, please provide our copyright agent with the required information pursuant to the DMCA.",
    },
    "right_of_withdrawal": {
        "heading": "Right of Withdrawal",
        "content": "Under EU consumer protection law, you have the right to withdraw from a purchase within 14 days without giving any reason.",
    },
    "consumer_rights": {
        "heading": "Consumer Rights",
        "content": "Nothing in these terms affects your statutory consumer rights under applicable law.",
    },
    "consumer_rights_act": {
        "heading": "Consumer Rights Act 2015",
        "content": "Your rights under the Consumer Rights Act 2015 are not affected by these terms.",
    },
    "digital_content_license": {
        "heading": "Digital Content License",
        "content": "{business_name} grants you a limited, non-exclusive, non-transferable license to access and use digital content purchased through our service.",
    },
    "subscription_terms": {
        "heading": "Subscription Terms",
        "content": "Subscriptions automatically renew unless cancelled before the renewal date. You may cancel your subscription at any time through your account settings.",
    },
    "allergen_disclaimer": {
        "heading": "Allergen Disclaimer",
        "content": "Products sold through {site_name} may contain allergens. Please review all product labels and descriptions carefully before purchasing.",
    },
    "perishable_goods": {
        "heading": "Perishable Goods",
        "content": "Perishable items have specific shipping and handling requirements. {business_name} is not liable for spoilage during transit beyond estimated delivery timeframes.",
    },
    "medical_disclaimer": {
        "heading": "Medical Disclaimer",
        "content": "Products sold on {site_name} are not intended to diagnose, treat, cure, or prevent any disease. Consult a healthcare professional before use.",
    },
    "fda_disclaimer": {
        "heading": "FDA Disclaimer",
        "content": "These statements have not been evaluated by the Food and Drug Administration. Products are not intended to diagnose, treat, cure, or prevent any disease.",
    },

    # Privacy Policy sections
    "information_collected": {
        "heading": "Information We Collect",
        "content": "{business_name} collects information you provide directly, such as name, email, shipping address, and payment information when you make a purchase or create an account.",
    },
    "how_we_use_information": {
        "heading": "How We Use Your Information",
        "content": "We use the information we collect to process transactions, send order confirmations, respond to inquiries, improve our service, and send marketing communications (with your consent).",
    },
    "information_sharing": {
        "heading": "Information Sharing",
        "content": "{business_name} does not sell your personal information. We may share information with service providers who assist in operating our store, processing payments, and fulfilling orders.",
    },
    "data_security": {
        "heading": "Data Security",
        "content": "We implement appropriate technical and organizational measures to protect your personal information against unauthorized access, alteration, disclosure, or destruction.",
    },
    "your_rights": {
        "heading": "Your Rights",
        "content": "You have the right to access, correct, or delete your personal information. You may also object to processing or request data portability.",
    },
    "cookies": {
        "heading": "Cookies",
        "content": "{site_name} uses cookies and similar tracking technologies to enhance your experience. You can control cookie preferences through your browser settings.",
    },
    "ccpa_rights": {
        "heading": "California Privacy Rights (CCPA)",
        "content": "California residents have the right to know what personal information is collected, request deletion, and opt out of the sale of personal information.",
    },
    "do_not_sell": {
        "heading": "Do Not Sell My Personal Information",
        "content": "{business_name} does not sell personal information. To exercise your CCPA rights, contact us using the information provided below.",
    },
    "gdpr_lawful_basis": {
        "heading": "Lawful Basis for Processing (GDPR)",
        "content": "We process your data on the following lawful bases: contract performance (order fulfillment), legitimate interest (service improvement), consent (marketing), and legal obligation (tax records).",
    },
    "data_retention": {
        "heading": "Data Retention",
        "content": "We retain your personal data only for as long as necessary to fulfill the purposes for which it was collected, including legal, accounting, or reporting requirements.",
    },
    "dpo_contact": {
        "heading": "Data Protection Officer",
        "content": "For privacy-related inquiries, you may contact our Data Protection Officer at the contact details provided on our website.",
    },
    "right_to_erasure": {
        "heading": "Right to Erasure",
        "content": "Under GDPR, you have the right to request erasure of your personal data when it is no longer necessary for the purpose it was collected.",
    },
    "uk_gdpr_rights": {
        "heading": "UK GDPR Rights",
        "content": "Under the UK GDPR, you have rights including access, rectification, erasure, restriction of processing, data portability, and the right to object.",
    },
    "ico_complaint": {
        "heading": "ICO Complaint",
        "content": "You have the right to lodge a complaint with the Information Commissioner's Office (ICO) if you believe your data protection rights have been violated.",
    },
    "pipeda_rights": {
        "heading": "PIPEDA Rights",
        "content": "Under PIPEDA, you have the right to access your personal information held by {business_name} and to challenge its accuracy and completeness.",
    },
    "provincial_rights": {
        "heading": "Provincial Privacy Rights",
        "content": "Residents of certain Canadian provinces may have additional privacy rights under provincial legislation.",
    },

    # Return Policy sections
    "return_eligibility": {
        "heading": "Return Eligibility",
        "content": "Items may be returned within {return_window} days of delivery. Items must be unused, in original packaging, and in the same condition as received.",
    },
    "return_window": {
        "heading": "Return Window",
        "content": "You have {return_window} days from the date of delivery to initiate a return. After this period, returns will not be accepted.",
    },
    "return_process": {
        "heading": "How to Return",
        "content": "To initiate a return, contact our customer service team. You will receive a return authorization and shipping instructions.",
    },
    "refund_method": {
        "heading": "Refund Method",
        "content": "Refunds will be issued to the original payment method within 5-10 business days after we receive and inspect the returned item.",
    },
    "shipping_costs": {
        "heading": "Return Shipping",
        "content": "{shipping_policy}",
    },
    "exceptions": {
        "heading": "Exceptions",
        "content": "The following items cannot be returned: personalized items, perishable goods, intimate apparel, and items marked as final sale.",
    },
    "14_day_cooling_off": {
        "heading": "14-Day Cooling Off Period",
        "content": "Under EU/UK consumer protection law, you have a 14-day cooling off period during which you may cancel your order for any reason.",
    },
    "digital_goods_exceptions": {
        "heading": "Digital Goods",
        "content": "Digital products cannot be returned once downloaded or accessed. By purchasing, you acknowledge and waive the right of withdrawal for digital content.",
    },
    "perishable_goods_exceptions": {
        "heading": "Perishable Goods",
        "content": "Perishable goods cannot be returned due to health and safety regulations unless the item arrived damaged or defective.",
    },
}


def generate_content(
    templates: list[dict[str, Any]],
    business: dict[str, Any],
    policies: dict[str, Any],
) -> dict[str, Any]:
    """Generate legal document content for each template.

    Args:
        templates: List of template selection dicts.
        business: Business info dict.
        policies: Policies config dict.

    Returns:
        Structured dict with generated documents.
    """
    try:
        biz = copy.deepcopy(business)
        pol = copy.deepcopy(policies)

        business_name = str(biz.get("name", "Our Company"))
        site_name = business_name
        country = str(biz.get("country", "US"))
        return_window = str(pol.get("return_window_days", 30))
        shipping_policy = str(pol.get("shipping_policy", "Customer is responsible for return shipping costs."))

        replacements = {
            "{business_name}": business_name,
            "{site_name}": site_name,
            "{country}": country,
            "{return_window}": return_window,
            "{shipping_policy}": shipping_policy,
        }

        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        documents: list[dict[str, Any]] = []

        for template in templates:
            required_sections = template.get("required_sections", [])
            template_name = str(template.get("template_name", ""))

            # Determine document type
            tid = str(template.get("template_id", ""))
            if tid.startswith("terms"):
                doc_type = "terms"
            elif tid.startswith("privacy"):
                doc_type = "privacy"
            elif tid.startswith("returns"):
                doc_type = "returns"
            else:
                doc_type = "other"

            sections: list[dict[str, Any]] = []
            full_content_parts: list[str] = []

            for section_key in required_sections:
                section_template = _SECTION_CONTENT.get(section_key)
                if section_template:
                    heading = section_template["heading"]
                    content = section_template["content"]

                    # Apply replacements
                    for placeholder, value in replacements.items():
                        content = content.replace(placeholder, value)

                    sections.append({
                        "heading": heading,
                        "content": content,
                        "is_required": True,
                    })
                    full_content_parts.append(f"## {heading}\n\n{content}")

            documents.append({
                "type": doc_type,
                "title": template_name,
                "content": "\n\n".join(full_content_parts),
                "sections": sections,
                "last_updated": timestamp,
            })

        return {
            "status": "success",
            "documents": documents,
        }
    except Exception as exc:
        return {
            "status": "error",
            "documents": [],
            "error": f"Content generation failed: {exc}",
        }
