`default_nettype none

module uart_tx #(
    parameter BAUD_DIV = 4
) (
    input wire clk,
    input wire rst_n,
    input wire send,
    input wire [7:0] data,
    output reg busy,
    output reg tx
);
    localparam integer BAUD_BITS = (BAUD_DIV > 1) ? $clog2(BAUD_DIV) : 1;
    localparam [BAUD_BITS-1:0] BAUD_LAST = BAUD_DIV[BAUD_BITS-1:0] - 2'd2;

    reg [BAUD_BITS-1:0] baud_count;
    reg [3:0] bit_index;
    reg [7:0] shift_data;

    always @(posedge clk) begin
        if (!rst_n) begin
            baud_count <= {BAUD_BITS{1'b0}};
            bit_index <= 4'd0;
            shift_data <= 8'd0;
            busy <= 1'b0;
            tx <= 1'b1;
        end else if (!busy) begin
            baud_count <= {BAUD_BITS{1'b0}};
            bit_index <= 4'd0;
            tx <= 1'b1;
            if (send) begin
                shift_data <= data;
                busy <= 1'b1;
                tx <= 1'b0;
            end
        end else if (baud_count == BAUD_LAST) begin
            baud_count <= {BAUD_BITS{1'b0}};
            case (bit_index)
                4'd8: begin
                    bit_index <= 4'd9;
                    tx <= 1'b1;
                end
                4'd9: begin
                    bit_index <= 4'd0;
                    busy <= 1'b0;
                    tx <= 1'b1;
                end
                default: begin
                    bit_index <= bit_index + 4'd1;
                    shift_data <= {1'b0, shift_data[7:1]};
                    tx <= shift_data[0];
                end
            endcase
        end else begin
            baud_count <= baud_count + 1'b1;
        end
    end
endmodule

`default_nettype wire
