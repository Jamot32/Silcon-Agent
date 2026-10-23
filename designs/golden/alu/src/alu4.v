`default_nettype none

module alu4 (
    input wire [3:0] a,
    input wire [3:0] b,
    input wire [2:0] op,
    output reg [3:0] result,
    output wire zero,
    output reg carry
);
    always @* begin
        result = 4'd0;
        carry = 1'b0;
        case (op)
            3'd0: {carry, result} = {1'b0, a} + {1'b0, b};
            3'd1: begin
                result = a - b;
                carry = (a >= b);
            end
            3'd2: result = a & b;
            3'd3: result = a | b;
            3'd4: result = a ^ b;
            3'd5: {carry, result} = {a, 1'b0};
            3'd6: begin
                result = {1'b0, a[3:1]};
                carry = a[0];
            end
            default: begin
                result = 4'd0;
                carry = 1'b0;
            end
        endcase
    end

    assign zero = (result == 4'd0);
endmodule

`default_nettype wire
